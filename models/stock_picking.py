from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def button_validate(self):
        """
        Force picking to done state using ONLY the qty actually received.
        Do NOT modify qty_done or quantity_done.
        """
        for picking in self:
            if picking.state in ('done', 'cancel'):
                continue

            _logger.info('Force Done: Completing picking %s using received quantities only', picking.name)

            # Mark move lines as done WITHOUT changing qty_done
            for move_line in picking.move_line_ids:
                move_line.write({'state': 'done'})

            # Mark stock moves as done WITHOUT changing quantity_done
            for move in picking.move_ids:
                move.write({'state': 'done'})

            # Mark picking as done
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
