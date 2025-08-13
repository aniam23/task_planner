from odoo import models, fields, api, _
from odoo.exceptions import UserError

class DeleteDynamicFieldWizard(models.TransientModel):
    _name = 'delete.dynamic.field.wizard'
    _description = 'Asistente para eliminar campos dinámicos'

    subtask_id = fields.Many2one(
        'subtask.board', 
        string='Subtarea',
        required=True,
        default=lambda self: self.env.context.get('active_id')
    )
    
    field_to_delete = fields.Many2one(
        'ir.model.fields',
        string="Campo a eliminar",
        required=True,
        domain="[('model', '=', 'subtask.board'), ('state', '=', 'manual')]"
    )

    def action_delete_dynamic_field(self):
        self.ensure_one()
        return self.subtask_id.with_context(
            active_field_id=self.field_to_delete.id
        ).action_delete_dynamic_field()