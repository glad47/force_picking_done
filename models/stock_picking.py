from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def button_validate(self):
        """
        Force picking to done state using ONLY the qty_done entered by user.
        Shows backorder wizard if partial quantity.
        """
        for picking in self:
            if picking.state in ('done', 'cancel'):
                continue

            _logger.info('Force Done: Processing picking %s', picking.name)

            # Check if there are partial quantities (need backorder)
            has_partial = False
            
            for move in picking.move_ids:
                user_qty_done = sum(move.move_line_ids.mapped('qty_done'))
                
                _logger.info('Move %s: qty_done = %s, demanded = %s', 
                             move.product_id.name, user_qty_done, move.product_uom_qty)

                if user_qty_done < move.product_uom_qty:
                    has_partial = True

            # If partial quantities, show backorder wizard
            if has_partial:
                return self._show_backorder_wizard(picking)

            # If full quantities, complete directly
            return self._force_done(picking)

        return True

    def _show_backorder_wizard(self, picking):
        """
        Show the standard Odoo backorder confirmation wizard.
        """
        backorder_wizard = self.env['stock.backorder.confirmation'].create({
            'pick_ids': [(4, picking.id)],
        })

        return {
            'name': 'Create Backorder?',
            'type': 'ir.actions.act_window',
            'res_model': 'stock.backorder.confirmation',
            'res_id': backorder_wizard.id,
            'view_mode': 'form',
            'target': 'new',
            'context': self.env.context,
        }

    def _force_done(self, picking):
        """
        Force the picking to done when full quantity received.
        """
        po_lines = self.env['purchase.order.line'].sudo()

        for move in picking.move_ids:
            user_qty_done = sum(move.move_line_ids.mapped('qty_done'))

            # Use sudo() to access purchase_line_id
            if move.sudo().purchase_line_id:
                po_lines |= move.sudo().purchase_line_id

            # Mark move lines as done
            done_move_lines = move.move_line_ids.filtered(lambda ml: ml.qty_done > 0)
            done_move_lines.write({'state': 'done'})

            # Update move
            move.write({
                'product_uom_qty': user_qty_done,
                'state': 'done',
            })

        # Mark picking as done
        picking.write({
            'state': 'done',
            'date_done': fields.Datetime.now(),
        })

        # Recompute PO qty_received (with sudo)
        if po_lines:
            po_lines.env.invalidate_all()
            po_lines._compute_qty_received()

        _logger.info('Force Done: Picking %s completed', picking.name)
        return True

    def _process_with_backorder(self):
        """
        Process picking and create backorder for remaining qty.
        """
        po_lines = self.env['purchase.order.line'].sudo()
        backorder_moves_data = []

        for move in self.move_ids:
            user_qty_done = sum(move.move_line_ids.mapped('qty_done'))
            remaining_qty = move.product_uom_qty - user_qty_done

            # Use sudo() to access purchase_line_id
            move_sudo = move.sudo()
            if move_sudo.purchase_line_id:
                po_lines |= move_sudo.purchase_line_id

            # Save data for backorder if remaining qty
            if remaining_qty > 0:
                backorder_moves_data.append({
                    'product_id': move.product_id.id,
                    'product_uom_qty': remaining_qty,
                    'product_uom': move.product_uom.id,
                    'location_id': move.location_id.id,
                    'location_dest_id': move.location_dest_id.id,
                    'name': move.name,
                    # Use sudo() to access purchase_line_id
                    'purchase_line_id': move_sudo.purchase_line_id.id if move_sudo.purchase_line_id else False,
                    'origin': move.origin,
                })

            # Mark move lines as done
            done_move_lines = move.move_line_ids.filtered(lambda ml: ml.qty_done > 0)
            done_move_lines.write({'state': 'done'})

            # Update move with received qty
            move.write({
                'product_uom_qty': user_qty_done,
                'state': 'done',
            })

        # Create backorder if needed
        if backorder_moves_data:
            backorder = self.copy({
                'name': '/',
                'move_ids': [],
                'move_line_ids': [],
                'backorder_id': self.id,
                'state': 'draft',
            })

            for move_vals in backorder_moves_data:
                move_vals['picking_id'] = backorder.id
                self.env['stock.move'].create(move_vals)

            backorder.action_confirm()
            backorder.action_assign()
            _logger.info('Backorder created: %s', backorder.name)

        # Mark original picking as done
        self.write({
            'state': 'done',
            'date_done': fields.Datetime.now(),
        })

        # Recompute PO qty_received (with sudo)
        if po_lines:
            po_lines.env.invalidate_all()
            po_lines._compute_qty_received()

        _logger.info('Force Done: Picking %s completed with backorder', self.name)

    def _force_done_no_backorder(self):
        """
        Process picking WITHOUT creating backorder.
        Remaining qty is ignored.
        """
        po_lines = self.env['purchase.order.line'].sudo()

        for move in self.move_ids:
            user_qty_done = sum(move.move_line_ids.mapped('qty_done'))

            # Use sudo() to access purchase_line_id
            if move.sudo().purchase_line_id:
                po_lines |= move.sudo().purchase_line_id

            # Mark move lines as done
            done_move_lines = move.move_line_ids.filtered(lambda ml: ml.qty_done > 0)
            done_move_lines.write({'state': 'done'})

            # Update move - set demand to received qty (no backorder)
            move.write({
                'product_uom_qty': user_qty_done,
                'state': 'done',
            })

        # Mark picking as done
        self.write({
            'state': 'done',
            'date_done': fields.Datetime.now(),
        })

        # Recompute PO qty_received (with sudo)
        if po_lines:
            po_lines.env.invalidate_all()
            po_lines._compute_qty_received()

        _logger.info('Force Done: Picking %s completed without backorder', self.name)


class StockBackorderConfirmation(models.TransientModel):
    _inherit = 'stock.backorder.confirmation'

    def process(self):
        """
        Override: Create backorder and complete original picking.
        """
        for picking in self.pick_ids:
            picking._process_with_backorder()
        return True

    def process_cancel_backorder(self):
        """
        Override: Complete without backorder.
        """
        for picking in self.pick_ids:
            picking._force_done_no_backorder()
        return True


class StockMove(models.Model):
    _inherit = 'stock.move'

    def _action_done(self, cancel_backorder=False):
        """Override to skip validation"""
        for move in self:
            move.write({'state': 'done'})
        return self