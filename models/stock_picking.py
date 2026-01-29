# -*- coding: utf-8 -*-

import logging
from odoo import models, fields, api, _
from odoo.tools import float_compare

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def button_force_done(self):
        """
        Force picking to DONE and create backorder for remaining qty.
        No validations, no wizards, no popups.
        """
        for picking in self:
            if picking.state in ('done', 'cancel'):
                continue

            _logger.info('FORCE DONE: %s', picking.name)

            # Confirm and assign if needed
            if picking.state == 'draft':
                picking.action_confirm()
            if picking.state in ('confirmed', 'waiting'):
                picking.action_assign()

            # Ensure move lines have qty_done set
            for move in picking.move_ids.filtered(lambda m: m.state not in ('done', 'cancel')):
                if not move.move_line_ids:
                    self.env['stock.move.line'].create({
                        'move_id': move.id,
                        'picking_id': picking.id,
                        'product_id': move.product_id.id,
                        'product_uom_id': move.product_uom.id,
                        'location_id': move.location_id.id,
                        'location_dest_id': move.location_dest_id.id,
                        'qty_done': move.product_uom_qty,
                        'company_id': move.company_id.id,
                    })
                else:
                    for line in move.move_line_ids:
                        if line.qty_done == 0:
                            line.qty_done = line.reserved_uom_qty or move.product_uom_qty

            # Create backorder for remaining quantities
            picking._force_backorder()

            # Force to done
            picking.move_ids.filtered(lambda m: m.state not in ('done', 'cancel')).write({
                'state': 'done',
                'date': fields.Datetime.now(),
            })
            
            picking.write({
                'state': 'done',
                'date_done': fields.Datetime.now(),
            })

            _logger.info('FORCE DONE: %s completed', picking.name)

        return True

    def _force_backorder(self):
        """Create backorder for remaining quantities."""
        self.ensure_one()
        
        backorder_moves_data = []
        
        for move in self.move_ids.filtered(lambda m: m.state not in ('done', 'cancel')):
            qty_done = sum(move.move_line_ids.mapped('qty_done'))
            qty_remaining = move.product_uom_qty - qty_done
            
            if float_compare(qty_remaining, 0, precision_rounding=move.product_uom.rounding) > 0 and qty_done > 0:
                backorder_moves_data.append({
                    'move': move,
                    'qty_done': qty_done,
                    'qty_remaining': qty_remaining,
                })

        if not backorder_moves_data:
            return False

        # Create backorder
        backorder = self.copy({
            'name': '/',
            'move_ids': [],
            'move_line_ids': [],
            'backorder_id': self.id,
            'state': 'draft',
        })

        for data in backorder_moves_data:
            move = data['move']
            
            # Reduce original move qty
            move.product_uom_qty = data['qty_done']
            
            # Create backorder move
            move.copy({
                'product_uom_qty': data['qty_remaining'],
                'picking_id': backorder.id,
                'state': 'draft',
                'move_line_ids': [],
            })

        backorder.action_confirm()
        backorder.action_assign()

        _logger.info('FORCE DONE: Created backorder %s', backorder.name)
        return backorder