from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def button_validate(self):
        """
        Prepare quantities and let Odoo's standard flow handle the rest,
        including the backorder wizard.
        """
        for picking in self:
            if picking.state in ('done', 'cancel'):
                continue

            _logger.info('Force Done: Processing picking %s', picking.name)

            for move in picking.move_ids:
                user_qty_done = sum(move.move_line_ids.mapped('qty_done'))
                _logger.info('Move %s: qty_done = %s, demanded = %s', 
                             move.product_id.name, user_qty_done, move.product_uom_qty)

        # Call standard Odoo validation - this will show backorder wizard if needed
        return super().button_validate()


class StockMove(models.Model):
    _inherit = 'stock.move'

    def _action_done(self, cancel_backorder=False):
        """
        Override to sync quantity_done with move lines and update PO.
        """
        for move in self:
            # Sync quantity from move lines
            user_qty_done = sum(move.move_line_ids.mapped('qty_done'))
            
            _logger.info('Move _action_done: %s qty_done = %s', 
                         move.product_id.name, user_qty_done)

        # Call standard Odoo _action_done
        result = super()._action_done(cancel_backorder=cancel_backorder)

        # Force recompute PO qty_received
        po_lines = self.env['purchase.order.line'].sudo()
        for move in self:
            if move.sudo().purchase_line_id:
                po_lines |= move.sudo().purchase_line_id

        if po_lines:
            po_lines.env.invalidate_all()
            po_lines._compute_qty_received()
            _logger.info('Recomputed qty_received for PO lines: %s', po_lines.ids)

        return result