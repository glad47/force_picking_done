# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.tools import float_compare
import logging

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def button_validate(self):
        """
        Override to always force DONE state.
        - No wizards, no popups
        - Auto creates backorders for partial qty
        - Skips all validations
        """
        for picking in self:
            if picking.state in ('done', 'cancel'):
                continue

            _logger.info('Force Validate: %s', picking.name)

            # Confirm and assign if needed
            if picking.state == 'draft':
                picking.action_confirm()
            if picking.state in ('confirmed', 'waiting'):
                picking.action_assign()

            # Ensure move lines exist and have qty_done
            picking._force_set_qty_done()

            # Create backorder for remaining qty
            picking._force_create_backorder()

            # Force moves to done
            for move in picking.move_ids.filtered(lambda m: m.state not in ('done', 'cancel')):
                move.write({
                    'state': 'done',
                    'date': fields.Datetime.now(),
                })
                # Update PO qty_received
                move._force_update_purchase_qty()

            # Force picking to done
            picking.write({
                'state': 'done',
                'date_done': fields.Datetime.now(),
            })

            _logger.info('Force Validate: %s completed', picking.name)

        return True

    def _force_set_qty_done(self):
        """Set qty_done on all move lines."""
        self.ensure_one()
        
        for move in self.move_ids.filtered(lambda m: m.state not in ('done', 'cancel')):
            if not move.move_line_ids:
                self.env['stock.move.line'].create({
                    'move_id': move.id,
                    'picking_id': self.id,
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

    def _force_create_backorder(self):
        """Create backorder for remaining quantities."""
        self.ensure_one()
        
        backorder_data = []
        
        for move in self.move_ids.filtered(lambda m: m.state not in ('done', 'cancel')):
            qty_done = sum(move.move_line_ids.mapped('qty_done'))
            qty_remaining = move.product_uom_qty - qty_done
            
            if float_compare(qty_remaining, 0, precision_rounding=move.product_uom.rounding) > 0 and qty_done > 0:
                backorder_data.append({
                    'move': move,
                    'qty_done': qty_done,
                    'qty_remaining': qty_remaining,
                })

        if not backorder_data:
            return False

        # Create backorder
        backorder = self.copy({
            'name': '/',
            'move_ids': [],
            'move_line_ids': [],
            'backorder_id': self.id,
            'state': 'draft',
        })

        for data in backorder_data:
            move = data['move']
            move.product_uom_qty = data['qty_done']
            
            move.copy({
                'product_uom_qty': data['qty_remaining'],
                'picking_id': backorder.id,
                'state': 'draft',
                'move_line_ids': [],
            })

        backorder.action_confirm()
        backorder.action_assign()
        
        _logger.info('Force Validate: Created backorder %s', backorder.name)
        return backorder


class StockMove(models.Model):
    _inherit = 'stock.move'

    def _force_update_purchase_qty(self):
        """Force update PO line qty_received."""
        for move in self:
            if move.purchase_line_id:
                po_line = move.purchase_line_id.sudo()
                po_line.invalidate_recordset(['qty_received'])
                po_line._compute_qty_received()
                _logger.info('Updated PO line %s qty_received', po_line.id)

    def _action_done(self, cancel_backorder=False):
        """Override to skip validations."""
        _logger.info('Force Done: _action_done called')
        return super()._action_done(cancel_backorder=cancel_backorder)

    def _check_qty_done(self):
        """Skip validation."""
        return

    def _check_move_qty_done(self):
        """Skip validation (Odoo 16+)."""
        return


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    def _check_reserved_qty(self):
        """Skip validation."""
        return