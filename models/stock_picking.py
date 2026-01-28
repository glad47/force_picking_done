from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def button_validate(self):
        """
        Use standard Odoo validation with backorder wizard.
        Works with both form view and barcode app.
        """
        _logger.info('Force Done: button_validate called for %s', self.mapped('name'))
        
        # Call standard Odoo - shows backorder wizard if partial
        return super().button_validate()

    def _action_done(self):
        """
        Override to ensure it completes even with partial quantities.
        Called by both regular validation and barcode app.
        """
        _logger.info('Force Done: _action_done called for %s', self.mapped('name'))
        return super()._action_done()


class StockMove(models.Model):
    _inherit = 'stock.move'

    def _action_done(self, cancel_backorder=False):
        """
        Override to:
        1. Skip strict validations
        2. Sync PO qty_received correctly
        Works with form view and barcode app.
        """
        _logger.info('Force Done: StockMove _action_done called')

        # Call standard Odoo _action_done
        result = super()._action_done(cancel_backorder=cancel_backorder)

        # Force recompute PO qty_received with sudo
        self._update_purchase_order_qty()

        return result

    def _update_purchase_order_qty(self):
        """
        Force PO lines to recompute qty_received.
        Uses sudo() so no purchase permission needed.
        """
        po_lines = self.env['purchase.order.line'].sudo()
        
        for move in self:
            if move.sudo().purchase_line_id:
                po_lines |= move.sudo().purchase_line_id
                _logger.info('Move %s: qty_done = %s, linked to PO line %s', 
                             move.product_id.name, 
                             move.quantity_done,
                             move.sudo().purchase_line_id.id)

        if po_lines:
            po_lines.env.invalidate_all()
            po_lines._compute_qty_received()
            _logger.info('Recomputed qty_received for PO lines: %s', po_lines.ids)

    def _check_qty_done(self):
        """
        Skip the quantity done validation.
        """
        _logger.info('Force Done: Skipping _check_qty_done validation')
        return

    def _check_move_qty_done(self):
        """
        Skip move quantity validation (Odoo 16+).
        """
        _logger.info('Force Done: Skipping _check_move_qty_done validation')
        return


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    def _check_reserved_qty(self):
        """
        Skip reserved quantity validation.
        """
        _logger.info('Force Done: Skipping _check_reserved_qty validation')
        return