from odoo import models, fields, api, _
from odoo.exceptions import UserError
import re
from lxml import etree
import logging
import json

_logger = logging.getLogger(__name__)

class DynamicFieldWizard(models.TransientModel):
    _name = 'dynamic.field.wizard'
    _description = 'Asistente para crear campos dinámicos por grupo exclusivo'
    
    dynamic_field_name = fields.Char(string="Nombre Técnico", required=True)
    dynamic_field_label = fields.Char(string="Etiqueta Visible", required=True)
    field_info = fields.Text(string="Valor Inicial")
    dynamic_field_type = fields.Selection([
        ('char', 'Texto'),
        ('integer', 'Entero'),
        ('float', 'Decimal'),
        ('date', 'Fecha'),
        ('datetime', 'Fecha/Hora'),
        ('boolean', 'Booleano'),
        ('selection', 'Selección')  # Añadido el tipo selección
        ],
        string="Tipo de Campo",
        required=True
    )
    
    # Campos para manejar opciones de selección
    selection_option_count = fields.Integer(
        string="Número de Opciones",
        default=1,
        compute='_compute_selection_option_count',
        store=True
    )
    
    
    selection_option_1 = fields.Char(string="Opción 1")
    selection_option_2 = fields.Char(string="Opción 2")
    selection_option_3 = fields.Char(string="Opción 3")
    selection_option_4 = fields.Char(string="Opción 4")
    selection_option_5 = fields.Char(string="Opción 5")
    selection_option_6 = fields.Char(string="Opción 6")
    selection_option_7 = fields.Char(string="Opción 7")
    selection_option_8 = fields.Char(string="Opción 8")
    selection_option_9 = fields.Char(string="Opción 9")
    selection_option_10 = fields.Char(string="Opción 10")
    selection_option_11 = fields.Char(string="Opción 11")
    selection_option_12 = fields.Char(string="Opción 12")
    selection_option_13 = fields.Char(string="Opción 13")
    selection_option_14 = fields.Char(string="Opción 14")
    selection_option_15 = fields.Char(string="Opción 15")
    selection_option_16 = fields.Char(string="Opción 16")
    selection_option_17 = fields.Char(string="Opción 17")
    selection_option_18 = fields.Char(string="Opción 18")
    selection_option_19 = fields.Char(string="Opción 19")
    selection_option_20 = fields.Char(string="Opción 20")
    subtask_id = fields.Many2one(
        'subtask.board',
        string="Subtarea Relacionada",
        default=lambda self: self._default_subtask_id()
    )

    def _default_subtask_id(self):
        """Obtiene la subtarea del contexto"""
        return self.env.context.get('default_subtask_id')
    
    # Grupo específico para este campo
    task_board_id = fields.Many2one(
        'task.board',
        string="Grupo Destino",
        required=True,
        readonly=True,
        default=lambda self: self._default_task_board_id()
    )

    def _default_task_board_id(self):
        """Obtiene el grupo de la subtarea asociada"""
        subtask_id = self.env.context.get('default_subtask_id')
        if subtask_id:
            subtask = self.env['subtask.board'].browse(subtask_id)
            if not subtask.task_id:
                raise UserError(_("La subtarea no está asignada a ningún grupo"))
            return subtask.task_id.id
        return False

    @api.depends('dynamic_field_type')
    def _compute_selection_option_count(self):
        """Calcula el número de opciones a mostrar"""
        for wizard in self:
            if wizard.dynamic_field_type == 'selection':
                # Si ya tiene opciones definidas, mantener el count
                if wizard.selection_option_count < 1:
                    wizard.selection_option_count = 1
            else:
                wizard.selection_option_count = 0

    def action_add_selection_option(self):
        """Añade una nueva opción al campo de selección"""
        self.ensure_one()
        if self.dynamic_field_type != 'selection':
            raise UserError(_("Solo puede agregar opciones a campos de tipo selección"))
        
        if self.selection_option_count < 10:
            self.selection_option_count += 1
        else:
            raise UserError(_("Máximo 10 opciones permitidas"))
        
        return {
            'type': 'ir.actions.act_window',
            'view_mode': 'form',
            'res_id': self.id,
            'res_model': 'dynamic.field.wizard',
            'target': 'new',
            'context': self.env.context,
        }

    def _get_selection_options(self):
        """Obtiene todas las opciones de selección ingresadas"""
        options = []
        for i in range(1, 11):
            option_value = getattr(self, f'selection_option_{i}', False)
            if option_value:
                # Usar el mismo valor para clave y etiqueta
                options.append((option_value, option_value))
        return options

    def action_create_dynamic_field(self):
        self.ensure_one()
        if not self.subtask_id:
            raise UserError(_("¡Error! Debe seleccionar una subtarea primero"))
        
        # Validación de campos requeridos
        if not self.dynamic_field_name or not self.dynamic_field_type:
            raise UserError(_("¡Error! El nombre técnico y tipo de campo son obligatorios"))
        
        # Validación especial para campos de selección
        if self.dynamic_field_type == 'selection':
            options = self._get_selection_options()
            if not options:
                raise UserError(_("¡Error! Debe agregar al menos una opción para campos de tipo selección"))
            
            # Preparar las opciones en formato Odoo
            selection_values = str(options)
        else:
            selection_values = False
        
        # Pasa los valores del wizard al subtask
        self.subtask_id.write({
            'dynamic_field_name': self.dynamic_field_name,
            'dynamic_field_label': self.dynamic_field_label,
            'dynamic_field_type': self.dynamic_field_type,
            'field_info': self.field_info,
        })
    
        # Llama al método en la subtarea pasando las opciones de selección
        return self.subtask_id.with_context(
            selection_values=selection_values
        ).action_create_dynamic_field()