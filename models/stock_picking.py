from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def button_validate(self):
        """
        Override default validation to force picking to done state
        without going through standard validation process.
        """
        for picking in self:
            if picking.state in ('done', 'cancel'):
                continue
            
            _logger.info('Force Done: Bypassing validation for picking %s', picking.name)
            
            # Process move lines - set qty_done and state
            for move_line in picking.move_line_ids:
                vals = {'state': 'done'}
                if move_line.qty_done == 0:
                    vals['qty_done'] = move_line.reserved_qty or move_line.reserved_uom_qty or 0
                move_line.write(vals)
            
            # Process stock moves - set quantity_done and state
            for move in picking.move_ids:
                vals = {'state': 'done'}
                if move.quantity_done == 0:
                    vals['quantity_done'] = move.product_uom_qty
                move.write(vals)
            
            # Force picking to done
            picking.write({
                'state': 'done',
                'date_done': fields.Datetime.now(),
            })
            
            _logger.info('Force Done: Picking %s set to done', picking.name)
        
        return True


class StockMove(models.Model):
    _inherit = 'stock.move'

    def _action_done(self, cancel_backorder=False):
        """
        Override to skip validation and just set to done
        """
        self.write({'state': 'done'})
        return self
