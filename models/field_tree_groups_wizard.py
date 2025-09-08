
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class FieldTreeGroupsWizard(models.TransientModel):
    _name = 'field.tree.groups.wizard'
    _description = 'Asistente para crear campos dinámicos por grupo exclusivo'

    # Datos del campo a crear
    dynamic_field_name = fields.Char(string="Nombre Técnico", required=True)
    dynamic_field_label = fields.Char(string="Etiqueta Visible", required=True)
    field_info = fields.Text(string="Valor Inicial")
    dynamic_field_type = fields.Selection([
        ('char', 'Texto'),
        ('text', 'Texto Largo'),
        ('html', 'HTML'),
        ('integer', 'Entero'),
        ('float', 'Decimal'),
        ('date', 'Fecha'),
        ('datetime', 'Fecha/Hora'),
        ('boolean', 'Booleano'),
        ('selection', 'Selección'),
    ], string="Tipo de Campo", required=True)

    # Relación al tablero (boards.planner) y al grupo (task.board)
    board_id = fields.Many2one('boards.planner', string='Tablero', required=False)
    task_id = fields.Many2one('task.board', string='Grupo')

    # Contador / control para las opciones de selección (aseguramos que exista)
    selection_option_count = fields.Integer(
        string="Número de Opciones",
        default=1
    )

    # Hasta 10 opciones de selección
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

    @api.model
    def default_get(self, fields_list):
        """Rellenar board_id y task_id automáticamente desde el contexto cuando existan."""
        res = super().default_get(fields_list)
        ctx = self.env.context or {}
        if ctx.get('default_board_id'):
            res['board_id'] = ctx.get('default_board_id')
        return res

    @api.model
    def _default_board_id(self):
        """Obtiene el tablero del contexto"""
        return self.env.context.get('board_id')

    def action_add_selection_option(self):
        """Aumentar el número de opciones (máx 10)."""
        self.ensure_one()
        if self.dynamic_field_type != 'selection':
            raise UserError(_("Solo puede agregar opciones si el tipo es 'Selección'"))
        if self.selection_option_count < 10:
            self.selection_option_count += 1
        else:
            raise UserError(_("Máximo 10 opciones permitidas"))
        # Recargar el wizard para que se muestren los campos nuevos en la vista
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': self.env.context,
        }

    def _get_selection_options(self):
        """Recoger las opciones de selección definidas en el wizard."""
        options = []
        for i in range(1, 11):
            val = getattr(self, f'selection_option_{i}', False)
            if val:
                # Odoo acepta una lista de tuplas para selection: [(key,label),...]
                options.append((val, val))
        return options

    def _get_task_board_auto(self):
        """Detecta automáticamente el grupo (task.board) al que se debe asociar el campo."""
        self.ensure_one()
        ctx = self.env.context or {}
        
        # 1. Desde el contexto del wizard
        if ctx.get('default_task_id'):
            return self.env['task.board'].browse(ctx['default_task_id'])
        
        # 2. Desde el tablero seleccionado en el wizard
        if self.board_id:
            task_board = self.env['task.board'].search([
                ('department_id', '=', self.board_id.id)
            ], limit=1)
            if task_board:
                return task_board
        
        # 3. Desde el registro activo
        active_model = ctx.get('active_model')
        active_id = ctx.get('active_id')
        if active_model == 'task.board' and active_id:
            task_board = self.env['task.board'].browse(active_id)
            if task_board.exists():
                return task_board
    
        raise UserError(_("No se pudo identificar el grupo/tablero para asociar el campo."))

    def action_create_dynamic_field(self):
        """Crear campo dinámico solo en el grupo detectado automáticamente."""
        self.ensure_one()

        # Validaciones básicas
        if not self.dynamic_field_name or not self.dynamic_field_type:
            raise UserError(_("El nombre técnico y el tipo de campo son obligatorios"))

        # Opciones de selección
        selection_values = False
        if self.dynamic_field_type == 'selection':
            opts = self._get_selection_options()
            if not opts:
                raise UserError(_("Debe agregar al menos una opción para campos tipo 'Selección'"))
            selection_values = str(opts)

        # Obtener el grupo automáticamente
        task_board = self._get_task_board_auto()

        # Asegurarse de que tenemos un tablero válido
        if not task_board.department_id:
            raise UserError(_("El grupo seleccionado no tiene un tablero asociado"))

        # Crear el campo dinámico
        try:
            context = {
                'selection_values': selection_values,
                'default_department_id': task_board.department_id.id,
                'creating_for_specific_board': True,
                'active_department_id': task_board.department_id.id  # Contexto adicional
            }

            return task_board.with_context(**context).action_create_dynamic_field_wizard(
                self.dynamic_field_name,
                self.dynamic_field_label or self.dynamic_field_name,
                self.dynamic_field_type,
                self.field_info
            )
        except Exception as e:
            _logger.exception("Error creando campo dinámico: %s", e)
            raise UserError(_("Error creando campo dinámico: %s") % str(e))
       