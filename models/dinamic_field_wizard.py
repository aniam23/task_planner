from odoo import models, fields, api, _
from odoo.exceptions import UserError

class DynamicFieldWizard(models.TransientModel):
    _name = 'dynamic.field.wizard'
    _description = 'Asistente para crear campos dinámicos'
    
    # Campos definidos en el wizard
    dynamic_field_name = fields.Char(string="Nombre Técnico del Campo", required=True)
    dynamic_field_label = fields.Char(string="Etiqueta Visible", required=True)
    dynamic_field_type = fields.Selection([
        ('char', 'Texto'),
        ('integer', 'Entero'),
        ('float', 'Decimal'),
        ('boolean', 'Booleano'),
        ('date', 'Fecha'),
        ('datetime', 'Fecha/Hora'),
        ('selection', 'Selección')],
        string="Tipo de Campo",
        required=True
    )
    selection_options = fields.Text(
        string="Opciones de Selección",
        help="Formato: clave:valor\nuno por línea"
    )
    subtask_id = fields.Many2one('subtask.board', string='Subtarea')

    def action_create_dynamic_field(self):
        self.ensure_one()
        if not self.subtask_id:
            raise UserError(_("¡Error! Debe seleccionar una subtarea primero"))
        
        # Validación de campos requeridos
        if not self.dynamic_field_name or not self.dynamic_field_type:
            raise UserError(_("¡Error! El nombre técnico y tipo de campo son obligatorios"))
        
        # Pasa los valores del wizard al subtask - CORRECCIÓN AQUÍ
        # Usa los mismos nombres que definiste en los campos del wizard
        self.subtask_id.write({
            'dynamic_field_name': self.dynamic_field_name,  # Antes era self.field_name
            'dynamic_field_label': self.dynamic_field_label,  # Antes era self.field_label
            'dynamic_field_type': self.dynamic_field_type,
            'selection_options': self.selection_options
        })
        
        # Llama al método en la subtarea
        return self.subtask_id.action_create_dynamic_field()