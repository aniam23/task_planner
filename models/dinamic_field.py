from odoo import models, fields, api
from odoo.exceptions import ValidationError

class DynamicFieldType(models.Model):
    _name = 'dynamic.field.type'
    _description = 'Tipos de Campos Dinámicos'
    _order = 'sequence, id'

    name = fields.Char('Nombre del Campo', required=True)
    technical_name = fields.Char(
        'Nombre Técnico',
        required=True,
        help="Usar solo letras minúsculas y guiones bajos (ej: fecha_entrega)",
        compute='_compute_technical_name',
        store=True
    )

    field_type = fields.Selection([
        ('char', 'Texto'),
        ('text', 'Texto Largo'),
        ('integer', 'Número Entero'),
        ('float', 'Número Decimal'),
        ('boolean', 'Verdadero/Falso'),
        ('date', 'Fecha'),
        ('datetime', 'Fecha y Hora'),
        ('selection', 'Selección'),
    ], string='Tipo de Campo', required=True, default='char')
    
    selection_options = fields.Text(
        'Opciones para Selección',
        help="Ingrese las opciones separadas por punto y coma (;)",
        default="Opción 1;Opción 2;Opción 3"
    )
    
    required = fields.Boolean('Requerido', default=False)
    sequence = fields.Integer('Secuencia', default=10)
    model_id = fields.Many2one(
        'ir.model',
        string='Aplicar a Modelo',
        domain=[('model', '=', 'task.board')],
        required=True
    )
    
    @api.depends('name')
    def _compute_technical_name(self):
        for record in self:
            if record.name:
                record.technical_name = 'x_' + record.name.lower().replace(' ', '_')
            else:
                record.technical_name = False
    
    @api.constrains('field_type', 'selection_options')
    def _check_selection_options(self):
        for record in self:
            if record.field_type == 'selection' and not record.selection_options.strip():
                raise ValidationError("Los campos de selección deben tener opciones definidas.")