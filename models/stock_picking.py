# -*- coding: utf-8 -*-

import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_is_zero

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def button_force_done(self):
        """
        FORCE DONE - Does everything:
        - Skips ALL validations
        - Creates backorder for remaining quantities
        - Forces state to DONE
        - Updates Purchase Order received quantities
        - Updates Sale Order delivered quantities
        - Updates stock moves and quants
        """
        _logger.info('FORCE DONE: called for %s', self.mapped('name'))

        for picking in self:
            if picking.state == 'done':
                _logger.info('FORCE DONE: %s already done, skipping', picking.name)
                continue
            
            if picking.state == 'cancel':
                _logger.warning('FORCE DONE: %s is cancelled, skipping', picking.name)
                continue

            # ========================================
            # STEP 1: Ensure picking is confirmed/assigned
            # ========================================
            if picking.state == 'draft':
                picking.action_confirm()
            if picking.state in ('confirmed', 'waiting'):
                picking.action_assign()

            # ========================================
            # STEP 2: Handle move lines - create if missing
            # ========================================
            for move in picking.move_ids.filtered(lambda m: m.state not in ('done', 'cancel')):
                # Create move lines if they don't exist
                if not move.move_line_ids:
                    picking._create_move_line_for_force(move)
                
                # Set quantity done on move lines
                for line in move.move_line_ids:
                    if line.qty_done == 0:
                        line.qty_done = line.reserved_uom_qty or (move.product_uom_qty - sum(move.move_line_ids.mapped('qty_done')))

            # ========================================
            # STEP 3: Create backorder for partial quantities
            # ========================================
            backorder = picking._create_backorder_forced()
            if backorder:
                _logger.info('FORCE DONE: Created backorder %s for %s', backorder.name, picking.name)

            # ========================================
            # STEP 4: Force validate moves and picking
            # ========================================
            picking._force_action_done()

            # ========================================
            # STEP 5: Update Purchase Order quantities
            # ========================================
            picking._update_purchase_order_qty()

            # ========================================
            # STEP 6: Update Sale Order quantities (if applicable)
            # ========================================
            picking._update_sale_order_qty()

            _logger.info('FORCE DONE: %s completed successfully', picking.name)

        return True

    def _create_move_line_for_force(self, move):
        """Create move line for moves without lines."""
        self.env['stock.move.line'].create({
            'move_id': move.id,
            'picking_id': self.id,
            'product_id': move.product_id.id,
            'product_uom_id': move.product_uom.id,
            'location_id': move.location_id.id,
            'location_dest_id': move.location_dest_id.id,
            'reserved_uom_qty': move.product_uom_qty,
            'qty_done': move.product_uom_qty,
            'company_id': move.company_id.id,
        })

    def _create_backorder_forced(self):
        """
        Create backorder for remaining quantities.
        Returns the backorder picking or False.
        """
        backorder_moves = self.env['stock.move']
        
        for move in self.move_ids.filtered(lambda m: m.state not in ('done', 'cancel')):
            qty_done = sum(move.move_line_ids.mapped('qty_done'))
            qty_remaining = move.product_uom_qty - qty_done
            
            precision = move.product_uom.rounding
            if float_compare(qty_remaining, 0, precision_rounding=precision) > 0:
                # There's remaining quantity - need backorder
                backorder_moves |= move

        if not backorder_moves:
            return False

        # Create backorder picking
        backorder_picking = self.copy({
            'name': '/',
            'move_ids': [],
            'move_line_ids': [],
            'backorder_id': self.id,
        })

        for move in backorder_moves:
            qty_done = sum(move.move_line_ids.mapped('qty_done'))
            qty_remaining = move.product_uom_qty - qty_done
            
            if float_compare(qty_remaining, 0, precision_rounding=move.product_uom.rounding) > 0:
                # Update original move quantity to what was done
                move.product_uom_qty = qty_done
                
                # Create backorder move for remaining
                move.copy({
                    'product_uom_qty': qty_remaining,
                    'picking_id': backorder_picking.id,
                    'state': 'draft',
                    'move_line_ids': [],
                })

        # Confirm and assign backorder
        backorder_picking.action_confirm()
        backorder_picking.action_assign()

        return backorder_picking

    def _force_action_done(self):
        """Force the picking and moves to done state."""
        # Use context to skip all checks
        picking = self.with_context(
            skip_sanity_check=True,
            skip_immediate=True,
            skip_backorder=True,
            skip_sms=True,
            skip_overprocessed_check=True,
            tracking_disable=True,
            mail_notrack=True,
            force_period_date=fields.Date.today(),
        )

        # Force moves to done
        for move in picking.move_ids.filtered(lambda m: m.state not in ('done', 'cancel')):
            # Ensure quantity_done is set
            if move.quantity_done == 0:
                move.quantity_done = sum(move.move_line_ids.mapped('qty_done'))
            
            # Force move line states
            for line in move.move_line_ids:
                if line.state != 'done':
                    line.write({'state': 'done'})

            # Force move to done
            move.write({'state': 'done', 'date': fields.Datetime.now()})
            
            # Update quants
            move._update_reserved_quantity_forced()

        # Force picking state
        picking.write({
            'state': 'done',
            'date_done': fields.Datetime.now(),
        })

    def _update_purchase_order_qty(self):
        """Update purchase order line received quantities."""
        if not self.purchase_id:
            return
        
        _logger.info('FORCE DONE: Updating PO %s quantities', self.purchase_id.name)
        
        for move in self.move_ids.filtered(lambda m: m.state == 'done'):
            # Find related PO line
            po_line = move.purchase_line_id
            if not po_line:
                continue
            
            # Calculate received quantity
            qty_done = move.quantity_done
            qty_received = po_line.qty_received + qty_done
            
            # Force update received quantity
            po_line.with_context(skip_compute=True).write({
                'qty_received': qty_received,
            })
            
            _logger.info('FORCE DONE: PO Line %s - qty_received updated to %s', 
                        po_line.id, qty_received)

        # Recompute PO state
        self.purchase_id._compute_invoice_status()

    def _update_sale_order_qty(self):
        """Update sale order line delivered quantities."""
        if not hasattr(self, 'sale_id') or not self.sale_id:
            return
        
        _logger.info('FORCE DONE: Updating SO %s quantities', self.sale_id.name)
        
        for move in self.move_ids.filtered(lambda m: m.state == 'done'):
            # Find related SO line
            so_line = move.sale_line_id
            if not so_line:
                continue
            
            # Force recompute delivered quantity
            so_line._compute_qty_delivered()
            
            _logger.info('FORCE DONE: SO Line %s - qty_delivered updated', so_line.id)


class StockMove(models.Model):
    _inherit = 'stock.move'

    def _update_reserved_quantity_forced(self):
        """Force update quants for the move."""
        for move in self:
            if move.state != 'done':
                continue
            
            for line in move.move_line_ids:
                # Get or create quants
                qty = line.qty_done
                if qty <= 0:
                    continue

                # Decrease source quant
                self.env['stock.quant']._update_available_quantity(
                    line.product_id,
                    line.location_id,
                    -qty,
                    lot_id=line.lot_id,
                    package_id=line.package_id,
                    owner_id=line.owner_id,
                )

                # Increase destination quant
                self.env['stock.quant']._update_available_quantity(
                    line.product_id,
                    line.location_dest_id,
                    qty,
                    lot_id=line.lot_id,
                    package_id=line.result_package_id,
                    owner_id=line.owner_id,
                )


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    # Add state field if not exists (for forcing)
    state = fields.Selection(related='move_id.state', store=True, readonly=False)