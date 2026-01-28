from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def button_validate(self):
        """
        Force picking to done state using ONLY the qty_done entered by user.
        PO will receive the same quantity.
        """
        for picking in self:
            if picking.state in ('done', 'cancel'):
                continue

            _logger.info('Force Done: Processing picking %s', picking.name)

            # Collect all PO lines to recompute later
            po_lines = self.env['purchase.order.line']

            for move in picking.move_ids:
                # Get qty_done entered by user on move lines
                user_qty_done = sum(move.move_line_ids.mapped('qty_done'))
                
                _logger.info('Move %s: qty_done = %s, demanded = %s', 
                             move.product_id.name, user_qty_done, move.product_uom_qty)

                # Collect linked PO lines
                if move.purchase_line_id:
                    po_lines |= move.purchase_line_id

                # DELETE extra move lines that have qty_done = 0
                # Keep only lines with actual qty_done
                move_lines_to_keep = move.move_line_ids.filtered(lambda ml: ml.qty_done > 0)
                move_lines_to_delete = move.move_line_ids - move_lines_to_keep
                
                if move_lines_to_delete:
                    move_lines_to_delete.unlink()

                # Update remaining move lines to done
                move_lines_to_keep.write({'state': 'done'})

                # IMPORTANT: Update product_uom_qty to match qty_done
                # This makes Odoo think we received exactly what was "expected"
                move.write({
                    'product_uom_qty': user_qty_done,  # Change demand to match received
                    'state': 'done',
                })

            # Mark picking as done
            picking.write({
                'state': 'done',
                'date_done': fields.Datetime.now(),
            })

            # Force recompute qty_received on PO lines
            if po_lines:
                po_lines.env.invalidate_all()
                po_lines._compute_qty_received()
                _logger.info('Recomputed qty_received for PO lines: %s', po_lines.ids)

            _logger.info('Force Done: Picking %s completed', picking.name)

        return True


class StockMove(models.Model):
    _inherit = 'stock.move'

    def _action_done(self, cancel_backorder=False):
        """Override to skip validation"""
        for move in self:
            move.write({'state': 'done'})
        return self