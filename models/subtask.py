from odoo import models, api, fields
from odoo.exceptions import ValidationError
from odoo.exceptions import UserError
from .boards import STATES
import logging
import json 
from datetime import datetime  
_logger = logging.getLogger(__name__)
class SubtaskBoard(models.Model):
    _name = 'subtask.board'
    _description = 'Subtarea del Planificador de Actividades'
    _inherit = ['mail.thread']
    
    sequence = fields.Integer(string='Sequence', default=10)
    completion_date = fields.Datetime(string="Timeline")
    drag = fields.Integer()
    files = fields.Many2many(comodel_name="ir.attachment", string="Archivos")
    name = fields.Char(string='Nombre de la tarea', required=True)
    task_id = fields.Many2one('task.board', string='Tarea', required=True)
    state = fields.Selection(STATES, default="new", string="Estado")
    # Campos para campos dinámicos
    dynamic_field_name = fields.Char(string="Nombre Técnico del Campo")
    dynamic_field_label = fields.Char(string="Etiqueta Visible")
    dynamic_field_type = fields.Selection([
        ('char', 'Texto'),
        ('integer', 'Entero'),
        ('float', 'Decimal'),
        ('boolean', 'Booleano'),
        ('date', 'Fecha'),
        ('datetime', 'Fecha/Hora'),
        ('selection', 'Selección')],
        string="Tipo de Campo"
    )
    selection_options = fields.Text(
        string="Opciones de Selección",
        help="Formato: clave:valor\nuno por línea"
    )
    dynamic_fields_data = fields.Text(
        string="Configuración de Campos",
        help="Almacena la configuración en JSON"
    )
    # Cambiamos a related field en lugar de computed para disponibilidad inmediata
    allowed_member_ids = fields.Many2many(
        'hr.employee',
        string='Miembros permitidos',
        related='task_id.allowed_member_ids',
        readonly=True,
        compute='compute_allowed_member_ids'
    )
    
    person = fields.Many2one(
        'hr.employee', 
        string='Responsable', 
        tracking=True,
        domain="[('id', 'in', allowed_member_ids)]"
    )
    
    activity_line_ids = fields.One2many('subtask.activity', 'subtask_id', string='Subtareas')
   
   
    def action_open_activity_tree(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'subtask.activity',
            'view_mode': 'tree,form',
            'target': 'current',
            'domain': [('subtask_id', '=', self.id)],  # Filtra por la subtarea actual
            'context': {
            'default_subtask_id': self.id,  # Establece la subtarea actual por defecto
            'search_default_subtask_id': self.id  # Filtra automáticamente
        },
        'name': f'Actividades de {self.name}'
    }

    @api.constrains('person', 'task_id')
    def _check_person_selection(self):
        for subtask in self:
            if subtask.task_id and subtask.task_id.department_id:
                pick_from_dept = getattr(subtask.task_id, 'pick_from_dept', True)
                if pick_from_dept:
                    if subtask.person and subtask.person.id not in subtask.task_id.department_id.member_ids.ids:
                        raise ValidationError(
                            "El empleado asignado debe ser miembro del departamento de la tarea principal"
                        )

    def action_custom_create_subtask(self):
        """Abre formulario para subtarea sin crear registro, pero con valores por defecto"""
        if not self.task_id:
            raise UserError("Debe existir una tarea principal para crear subtareas")
    
        # Prepara valores por defecto sin crear el registro
        default_values = {
            'task_id': self.task_id.id,
            'name': f"Subtarea de {self.task_id.name}",
        }
    
        # Si el modelo tiene el campo y la tarea principal también
        if hasattr(self.task_id, 'allowed_member_ids'):
            default_values['allowed_member_ids'] = [(6, 0, self.task_id.allowed_member_ids.ids)]
    
        return {
            'name': 'Nueva Subtarea',
            'type': 'ir.actions.act_window',
            'res_model': 'subtask.board',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_' + key: value for key, value in default_values.items()
            }
        }

    def action_create_dynamic_field(self):
        """Crea nuevo campo dinámico sin mensaje de confirmación"""
        self.ensure_one()
        
        if not self.dynamic_field_name or not self.dynamic_field_type:
            raise UserError("Debe especificar nombre y tipo de campo")
        
        field_name = self._generate_valid_field_name(self.dynamic_field_name)
        
        try:
            # Crear campo en modelo
            self._create_field_in_model(field_name)
            
            # Actualizar vista
            self._update_tree_view(field_name)
            
            # Guardar metadatos
            self._store_field_metadata(field_name)
            
            # Recarga silenciosa
            return {'type': 'ir.actions.client', 'tag': 'reload'}
            
        except Exception as e:
            _logger.error("Error creando campo: %s", str(e))
            raise UserError(f"Error al crear campo: {str(e)}")

    def action_delete_dynamic_field(self):
        """Elimina un campo dinámico seleccionado sin mensaje"""
        self.ensure_one()

        if not self.dynamic_field_to_delete:
            raise UserError("Debe seleccionar un campo para eliminar")

        try:
            field_name = self.dynamic_field_to_delete.name

            # 1. Eliminar de la base de datos
            self._remove_column_from_table(field_name)

            # 2. Eliminar definición del campo
            self.dynamic_field_to_delete.unlink()

            # 3. Limpiar metadatos
            self._clean_field_metadata(field_name)

            # Recarga silenciosa
            return {'type': 'ir.actions.client', 'tag': 'reload'}

        except Exception as e:
            _logger.error("Error eliminando campo: %s", str(e))
            raise UserError(f"Error al eliminar campo: {str(e)}")

    def _generate_valid_field_name(self, name):
        """Genera un nombre de campo válido siguiendo las convenciones de Odoo"""
        import re
        # Eliminar caracteres no permitidos y convertir a snake_case
        name = re.sub(r'[^a-zA-Z0-9_]', '', name.lower().replace(' ', '_'))
        # Asegurar que empiece con x_ para campos personalizados
        if not name.startswith('x_'):
            name = f'x_{name}'
        # Validar que no empiece con número después del x_
        if len(name) > 2 and name[2].isdigit():
            name = f'x_field_{name[2:]}'
        return name       
    
    def _create_field_in_model(self, field_name):
        """Crea el campo técnico en el modelo"""
        model = self.env['ir.model'].sudo().search([('model', '=', self._name)])
        if not model:
            raise UserError("Modelo no encontrado en el sistema")

        field_description = self.dynamic_field_label or field_name.replace('_', ' ').title()

        field_vals = {
            'name': field_name,
            'model_id': model.id,
            'field_description': field_description,
            'ttype': self.dynamic_field_type,
            'state': 'manual',
            'store': True,
            'required': False,
        }

        # Manejar campos de selección
        if self.dynamic_field_type == 'selection' and self.selection_options:
            selection = []
            for line in self.selection_options.split('\n'):
                if line.strip() and ':' in line:
                    key, val = map(str.strip, line.split(':', 1))
                    selection.append((key, val))
            if selection:
                field_vals['selection'] = str(selection)

        # Crear el campo
        field = self.env['ir.model.fields'].sudo().create(field_vals)

        # Añadir columna a la base de datos
        self._add_column_to_table(field_name, self.dynamic_field_type)

        return field

    def _add_column_to_table(self, field_name, field_type):
        """Crea la columna en la base de datos para el nuevo campo"""
        # Mapeo de tipos Odoo a tipos PostgreSQL
        type_mapping = {
            'char': 'varchar',
            'integer': 'integer',
            'float': 'numeric',
            'boolean': 'boolean',
            'date': 'date',
            'datetime': 'timestamp',
            'selection': 'varchar',
        }
        
        if field_type not in type_mapping:
            raise UserError(f"Tipo de campo no soportado: {field_type}")
        
        column_type = type_mapping[field_type]
        
        # Para campos char, necesitamos especificar una longitud
        if field_type == 'char':
            column_type += '(255)'
        
        # Para campos float, especificamos precisión
        elif field_type == 'float':
            column_type += '(16,2)'
        
        # Ejecutar el SQL directamente
        query = """
            ALTER TABLE %s ADD COLUMN IF NOT EXISTS %s %s
        """ % (self._table, field_name, column_type)
        
        try:
            self._cr.execute(query)
            self._cr.commit()
        except Exception as e:
            _logger.error("Error al agregar columna a la tabla: %s", str(e))
            raise UserError(f"No se pudo crear la columna en la base de datos: {str(e)}")

    def _update_tree_view(self, field_name):
        """Método corregido para agregar columnas dinámicas en el tree view"""
        try:
            # 1. Obtener la vista tree original
            view = self.env.ref('task_planner.view_subtask_tree')

            # 2. Crear la estructura XML para la nueva columna
            arch = """
            <data>
                <xpath expr="//tree/field[@name='completion_date']" position="after">
                    <field name="%s" string="%s" optional="show" %s/>
                </xpath>
            </data>
            """ % (
                field_name,
                self.dynamic_field_label or field_name.replace('_', ' ').title(),
                self._get_tree_widget_for_field()
            )

            # 3. Crear la extensión de vista
            self.env['ir.ui.view'].create({
                'name': f'subtask.board.tree.dynamic.{field_name}',
                'model': self._name,
                'inherit_id': view.id,
                'arch': arch,
                'type': 'tree',
                'priority': 99,
            })

            # 4. Forzar la actualización de la vista
            self.env['ir.ui.view'].clear_caches()
            _logger.info(f"Columna {field_name} agregada correctamente después de completion_date")

        except Exception as e:
            _logger.error(f"Error al actualizar tree view: {str(e)}")
            raise UserError(f"No se pudo agregar la columna al listado: {str(e)}")

    def _store_field_metadata(self, field_name):
        """Almacena la configuración del campo para referencia futura"""
        try:
            # Convertir datetime a string antes de serializar
            created_at = fields.Datetime.now()
            if isinstance(created_at, datetime):
                created_at = created_at.isoformat()
            
            field_data = {
                'name': field_name,
                'label': self.dynamic_field_label,
                'type': self.dynamic_field_type,
                'created_at': created_at,  # Usamos el valor ya convertido
                'created_by': self.env.user.id,
            }
            
            if self.dynamic_field_type == 'selection' and self.selection_options:
                field_data['options'] = self.selection_options.split('\n')
        
            # Función para serializar objetos complejos
            def json_serial(obj):
                if isinstance(obj, datetime):
                    return obj.isoformat()
                raise TypeError(f"Type {type(obj)} not serializable")
            
            # Convertir a JSON con el manejador personalizado
            self.dynamic_fields_data = json.dumps(
                field_data, 
                default=json_serial,  # <-- Usamos nuestra función de serialización
                indent=2
            )
            
        except Exception as e:
            _logger.error("Error al almacenar metadatos: %s", str(e))
            raise UserError(f"No se pudo guardar la configuración: {str(e)}")

    
    def _get_tree_widget_for_field(self):
        """Devuelve el atributo widget apropiado según el tipo de campo"""
        widget_map = {
            'boolean': 'boolean',
            'selection': 'selection',
            'date': 'daterange',
            'datetime': 'datetime',
            'float': 'float',
            'integer': 'integer',
        'many2one': 'many2one_avatar_user',  # Para mantener consistencia con tu campo 'person'
        }
        widget = widget_map.get(self.dynamic_field_type, '')
        return f'widget="{widget}"' if widget else ''

   
       
    @api.depends('task_id')
    def compute_allowed_member_ids(self):
        self.allowed_member_ids = self.task_id.allowed_member_ids

   

 
