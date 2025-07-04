from odoo import models, api, fields
from odoo.exceptions import ValidationError
from .boards import STATES
from odoo.models import BaseModel
import re
import json
import traceback
from xml.etree import ElementTree as ET
import logging
from lxml import etree
_logger = logging.getLogger(__name__)
class TaskBoard(models.Model):
    _name = 'task.board'
    _description = 'Activity Planner Task'
    _inherit = ['mail.thread']
    completion_date = fields.Datetime(string="Timeline")
    department_id = fields.Many2one(
        'boards.planner', 
        string="Department", 
        ondelete='cascade',
        required=True
    )
    dynamic_field_list = fields.Many2many(
    'ir.model.fields',
    string='Campos Dinámicos',
    compute='_compute_dynamic_fields',
    store=False
    )
    sequence = fields.Integer(string='Sequence', default=10)
    drag = fields.Integer()
    files = fields.Many2many('ir.attachment', string="Files")
    name = fields.Char(string="Task", required=True)
    person = fields.Many2one(
        'hr.employee',
        string='Assigned To',
        tracking=True,
        required=True,
        domain="[('id', 'in', allowed_member_ids)]"
    )
    color = fields.Integer(string='Color Index', compute='_compute_color_from_state', store=True)
    status = fields.Selection(STATES, default="new", string="State")
    subtask_ids = fields.One2many('subtask.board', 'task_id', string='Subtasks')
    allowed_member_ids = fields.Many2many(
        'hr.employee',
        compute='_compute_allowed_members',
        string='Allowed Members'
    )
    color = fields.Integer(string='Color Index', compute='_compute_color_from_state', store=True)
    completed_subtasks = fields.Integer(
        string="Completed Subtasks",
        compute='_compute_progress',
        store=True,
        default=0  # Añadir valor por defecto
    )
    
    total_subtasks = fields.Integer(
        string="Total Subtasks",
        compute='_compute_progress',
        store=True,
        default=0  # Añadir valor por defecto
    )

    progress = fields.Float(
    string="Progress", 
    compute='_compute_progress', 
    store=True,
    group_operator="avg",
    default=0.0
    )

    show_subtasks = fields.Boolean(string="Show Subtasks", default=True)
    parent_id = fields.Many2one('task.board', 'Parent Task', index=True, ondelete='cascade')
    child_ids = fields.One2many('task.board', 'parent_id', 'Sub-tasks')
     # Campos principales existentes (se mantienen igual)
    completion_date = fields.Datetime(string="Timeline")
    department_id = fields.Many2one('boards.planner', string="Department", ondelete='cascade', required=True)
    sequence = fields.Integer(string='Sequence', default=10)
    drag = fields.Integer()
    files = fields.Many2many('ir.attachment', string="Files")
    name = fields.Char(string="Task", required=True)
    person = fields.Many2one('hr.employee', string='Assigned To', tracking=True, required=True, domain="[('id', 'in', allowed_member_ids)]")
    status = fields.Selection(STATES, default="new", string="State")
    subtask_ids = fields.One2many('subtask.board', 'task_id', string='Subtasks')
    show_subtasks = fields.Boolean(string="Show Subtasks", default=True)
    parent_id = fields.Many2one('task.board', 'Parent Task', index=True, ondelete='cascade')
    child_ids = fields.One2many('task.board', 'parent_id', 'Sub-tasks')
    # Añade esto junto con los otros campos dinámicos
    selection_options = fields.Text(
    string="Opciones de Selección",
    help="Ingrese opciones en formato clave:valor, una por línea. Ejemplo:\nopcion1:Opción 1\nopcion2:Opción 2"
    )
    dynamic_field_type = fields.Selection([
        ('char', 'Texto'),
        ('integer', 'Número Entero'),
        ('float', 'Decimal'),
        ('boolean', 'Booleano'),
        ('selection', 'Selección'),
        ('date', 'Fecha'),
        ('datetime', 'Fecha/Hora'),
        ('text', 'Texto Largo')],
        string='Tipo de Campo')
    
    dynamic_field_name = fields.Char(string='Nombre Técnico')
    dynamic_field_label = fields.Char(string='Etiqueta')
    selection_options = fields.Text(string='Opciones de Selección (clave:valor)')
    dynamic_fields_data = fields.Text(string='Campos Dinámicos')
    dynamic_field_names = fields.Text(
    string="Campos Dinámicos",
    compute='_compute_dynamic_fields',
    store=False
    )

    #eliminar campos dinamicos 
    
    def action_remove_dynamic_field(self):
        """Elimina un campo dinámico asegurándose de borrar referencias y la columna DB."""
        self.ensure_one()
        if not self.dynamic_field_name:
            raise ValidationError("Debe especificar el nombre del campo a eliminar")
        # Generar nombre de campo válido 
        field_name = self._generate_valid_field_name(self.dynamic_field_name)
        try:
            # Eliminar vistas que contengan el campo (con y sin prefijo 'x_')
            field_names_to_search = [field_name, field_name.lstrip('x_')]
            for fname in field_names_to_search:
                views = self.env['ir.ui.view'].search([('arch_db', 'ilike', fname)])
                for view in views:
                    if fname in (view.arch_db or ''):
                        _logger.info(f"Eliminando vista {view.name} que contiene campo {fname}")
                        view.unlink()

            # Eliminar campo en ir.model.fields (manejo protegido)
            field = self.env['ir.model.fields'].search([
                ('model', '=', self._name),
                ('name', '=', field_name)
            ], limit=2)
            
            if field:
                try:
                    field.unlink()
                except Exception as e:
                    _logger.warning(f"Eliminación normal falló para {field_name}: {e}")
                    # Método forzado si falla
                    self._force_remove_field(field_name)
            # return {
            #     'type': 'ir.actions.client',
            #     'tag': 'reload',
                
            # }
            #  Eliminar columna física en la tabla SQL (si existe)
            self._remove_column_from_table(field_name)

            # Verificar eliminación completa
            self._verify_field_removal(field_name)

            # # Recargar definición del modelo para que Odoo no intente acceder al campo eliminado
            # self._reload_model_definition()

            return {
                'type': 'ir.actions.client',
                'tag': 'reload',
            }

        except Exception as e:
            _logger.error(f"Error al eliminar campo dinámico: {e}")
            raise ValidationError(f"Error al eliminar campo: {e}")

    def _force_remove_field(self, field_name):
        """Eliminación forzada para campos protegidos"""
        self.env.cr.execute("""
            UPDATE ir_model_fields SET state = 'manual'
            WHERE model = %s AND name = %s
        """, [self._name, field_name])
        self.env.cr.execute("""
            DELETE FROM ir_model_fields
            WHERE model = %s AND name = %s
        """, [self._name, field_name])
        self.env.cr.execute("""
            DELETE FROM ir_default
            WHERE field_name = %s AND model = %s
        """, [field_name, self._name])
        self.env.cr.commit()

    def _remove_column_from_table(self, field_name):
        """Eliminar columna física si existe"""
        # Validar nombre de campo para DB (usamos función de Odoo)
        if not self._is_valid_db_identifier(field_name):
            raise ValidationError("Nombre de campo inválido para PostgreSQL")

        self.env.cr.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = %s AND column_name = %s
        """, [self._table, field_name])

        if self.env.cr.fetchone():
            self.env.cr.execute(f'ALTER TABLE "{self._table}" DROP COLUMN IF EXISTS "{field_name}"')

    def _verify_field_removal(self, field_name):
        """Verificar que el campo fue eliminado"""
        errors = []
        if self.env['ir.model.fields'].search([('model', '=', self._name), ('name', '=', field_name)], limit=1):
            errors.append("El campo sigue existiendo en ir.model.fields")
        if field_name in self.env[self._name]._fields:
            errors.append("El campo sigue en la definición del modelo")
        self.env.cr.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = %s AND column_name = %s
        """, [self._table, field_name])
        if self.env.cr.fetchone():
            errors.append("La columna sigue existiendo en la base de datos")

        if errors:
            raise ValidationError("El campo no se eliminó completamente:\n" + "\n".join(errors))

    def _reload_model_definition(self):
        """Recarga la definición del modelo para que no use el campo eliminado"""
        # Usamos _setup_fields y _setup_complete para recargar
        self.env[self._name]._setup_fields()
        self.env[self._name]._setup_complete()
        
    #creacion de campos dinamicos
    def action_create_dynamic_field(self):
        """asegura que el campo aparezca en las vistas"""
        self.ensure_one()
        try:
            # Validaciones
            if not self.dynamic_field_type:
                raise ValidationError("Debe seleccionar un tipo de campo")
            if not self.dynamic_field_name:
                raise ValidationError("El nombre técnico es obligatorio")
            
            # Generar nombre válido
            field_name = self._generate_valid_field_name(self.dynamic_field_name)
            
            # Crear el campo en el modelo
            self._create_field_in_model(field_name)
            
            # Actualizar vistas de forma más robusta
            self._update_views_completely(field_name)
            
            return {
                'type': 'ir.actions.client',
                'tag': 'reload',
                'params': {'wait': True}
            }
        except Exception as e:
            _logger.error("Error completo: %s", traceback.format_exc())
            raise ValidationError(f"Error al crear campo: {str(e)}")

    def _generate_valid_field_name(self, name):
        """
        Genera un nombre técnico válido para un campo de Odoo:
        """
        # Primero limpiamos el nombre
        name = name.lower()
        name = re.sub(r'\s+', '_', name)   
        name = re.sub(r'[^a-z0-9_]', '', name) 
        if not name.startswith('x_'):
            name = f"x_{name}"
        if len(name) > 2 and name[2].isdigit():
            name = f"x_field_{name[2:]}"
        return name

    def _update_views_completely(self, field_name):
        """Método mejorado para actualizar todas las vistas necesarias"""
        try:
            # 1. Actualizar vista tree
            self._update_specific_view(
                view_xml_id='task_planner.activity_planner_task_view_tree',
                view_type='tree',
                field_name=field_name
            )
            # 2. Actualizar vista form
            self._update_specific_view(
                view_xml_id='task_planner.activity_planner_details_view_form',
                view_type='form',
                field_name=field_name
            )
            # 3. Actualizar vista kanban si existe
            try:
                self._update_specific_view(
                    view_xml_id='task_planner.view_task_kanban',
                    view_type='kanban',
                    field_name=field_name
                )
            except:
                _logger.warning("No se encontró vista kanban, omitiendo")
            # 4. Forzar actualización del cache de vistas
            self.env['ir.ui.view'].clear_caches()
        except Exception as e:
            _logger.error("Error actualizando vistas: %s", str(e))
            raise

    def _update_specific_view(self, view_xml_id, view_type, field_name):
        """Actualiza una vista específica asegurando que el campo se agregue"""
        try:
            # Obtener la vista base
            base_view = self.env.ref(view_xml_id)
            # Crear nombre único para la vista heredada
            inherit_view_name = f"{self._name}.{view_type}.inherit.{field_name}"
            # Buscar si ya existe una vista heredada
            inherited_view = self.env['ir.ui.view'].search([
                ('name', '=', inherit_view_name),
                ('model', '=', self._name)
            ], limit=1)
            # Generar el archivo XML para la vista
            arch = self._generate_view_arch_with_field(
                base_view=base_view,
                view_type=view_type,
                field_name=field_name
            )
            if inherited_view:
                # Actualizar vista existente
                inherited_view.write({'arch': arch})
            else:
                # Crear nueva vista heredada
                self.env['ir.ui.view'].create({
                    'name': inherit_view_name,
                    'type': view_type,
                    'model': self._name,
                    'inherit_id': base_view.id,
                    'arch': arch,
                    'active': True
                })
        except Exception as e:
            _logger.error("Error actualizando vista %s: %s", view_xml_id, str(e))
            raise

    def _generate_view_arch_with_field(self, base_view, view_type, field_name):
        """Genera el XML para la vista con el nuevo campo"""
        # Determinar la mejor posición para insertar el campo
        position_info = self._get_best_position_for_field(base_view, view_type)
        # Configurar atributos del campo
        field_attrs = {
            'name': field_name,
            'string': self.dynamic_field_label,
            'optional': 'show'
        }
        # Añadir widgets especiales según el tipo de campo
        if self.dynamic_field_type == 'selection':
            field_attrs['widget'] = 'selection'
        elif self.dynamic_field_type in ['date', 'datetime']:
            field_attrs['widget'] = self.dynamic_field_type
        # Construir el XML completo
        return f"""
        <data>
            <xpath expr="{position_info['xpath']}" position="{position_info['position']}">
                <field {' '.join([f'{k}="{v}"' for k, v in field_attrs.items()])}/>
            </xpath>
        </data>
        """

    def _get_best_position_for_field(self, base_view, view_type):
        """Determina la mejor posición para insertar el campo en la vista"""
        try:
            doc = etree.fromstring(base_view.arch)
            if view_type == 'form':
                # Intentar insertar después del último campo
                last_field = doc.xpath("(//field[not(ancestor::field)])[last()]")
                if last_field:
                    return {
                        'xpath': f"//field[@name='{last_field[0].get('name')}']",
                        'position': 'after'
                    }
                # Si no hay campos, insertar en el sheet principal
                sheet = doc.xpath("//sheet")[0] if doc.xpath("//sheet") else None
                if sheet:
                    return {
                        'xpath': f"//sheet[@name='{sheet.get('name', '')}']",
                        'position': 'inside'
                    }
            elif view_type == 'tree':
                # Insertar después del último campo visible
                last_field = doc.xpath("(//field[not(@invisible)])[last()]") or doc.xpath("(//field)[last()]")
                if last_field:
                    return {
                        'xpath': f"//field[@name='{last_field[0].get('name')}']",
                        'position': 'after'
                    }
            # Posición por defecto si no se encuentra un buen lugar
            return {
                'xpath': "/*",
                'position': 'inside'
            } 
        except Exception as e:
            _logger.warning("Error analizando vista: %s", str(e))
            return {
                'xpath': "/*",
                'position': 'inside'
            }

    def _create_field_in_model(self, field_name):
        """Crea el campo dinámico en el modelo"""
        field_type = self.dynamic_field_type
        if not field_type:
            raise ValidationError("Debe seleccionar un tipo de campo.")
        # Validar opciones si es un campo de selección
        selection = False
        if field_type == 'selection':
            selection = []
            if not self.selection_options:
                raise ValidationError("Debe proporcionar opciones para el campo de selección.")
            for line in self.selection_options.strip().splitlines():
                if ':' not in line:
                    raise ValidationError("Cada opción debe tener el formato clave:valor.")
                key, val = line.split(':', 1)
                selection.append((key.strip(), val.strip()))
            # Guardar en JSON para usarlo luego si se requiere
            self.dynamic_fields_data = json.dumps(selection)
        model = self.env['ir.model'].search([('model', '=', self._name)], limit=1)
        if not model:
            raise ValidationError(f"No se encontró el modelo '{self._name}'.")
        field_values = {
            'name': field_name,
            'model_id': model.id,
            'field_description': self.dynamic_field_label or field_name,
            'ttype': field_type,
            'state': 'manual',  
            'required': False,
            'readonly': False,
            'index': False,
        }
        if selection:
            field_values['selection'] = json.dumps(selection)
        # Crear el campo en ir.model.fields
        self.env['ir.model.fields'].create(field_values)
            # Manejar campos de selección
        if self.dynamic_field_type == 'selection' and self.selection_options:
                selection = []
                for line in self.selection_options.split('\n'):
                    if line.strip() and ':' in line:
                        key, val = map(str.strip, line.split(':', 1))
                        selection.append((key, val))
                field_vals['selection'] = str(selection)
            # Crear el campo técnico
                self.env['ir.model.fields'].sudo().create(field_vals)
            # Añadir la columna a la tabla
                self._add_column_to_table(field_name)
            # Limpiar caché para que el campo esté disponible inmediatamente
                self.env.registry.clear_cache()

    # def _reload_model_definition(self):
    #     """Recarga la definición del modelo actual desde la base de datos."""
    #     if isinstance(self.env[self._name], BaseModel):
    #         self.env[self._name]._setup_fields()
    #         self.env[self._name]._setup_complete()

    def _add_column_to_table(self, field_name):
        """Añade la columna a la tabla en la base de datos"""
        column_type = {
            'char': 'VARCHAR',
            'integer': 'INTEGER',
            'float': 'NUMERIC',
            'boolean': 'BOOLEAN',
            'selection': 'VARCHAR',
            'date': 'DATE',
            'datetime': 'TIMESTAMP',
            'text': 'TEXT'
        }.get(self.dynamic_field_type, 'VARCHAR')

        if column_type == 'VARCHAR':
            column_type += '(255)'

        query = sql.SQL("ALTER TABLE {} ADD COLUMN IF NOT EXISTS {} {}").format(
            sql.Identifier(self._table),
            sql.Identifier(field_name),
            sql.SQL(column_type)
        )

        try:
            self.env.cr.execute(query)
        except Exception as e:
            _logger.error("Error añadiendo columna: %s", str(e))
            raise ValidationError("Error técnico al crear el campo en la base de datos")

    def action_open_dynamic_field_creator(self):
        """Abrir diálogo para crear campo dinámico"""
        self.ensure_one()
        return {
            'name': ('Agregar Campo Dinámico'),
            'type': 'ir.actions.act_window',
            'res_model': 'task.board',
            'res_id': self.id,
            'view_mode': 'form',
            'view_id': self.env.ref('task_planner.view_task_board_dynamic_fields_form').id,
            'target': 'new',
        }

    def action_add_subtask (self):
        return {
        'type': 'ir.actions.act_window',
        'name': 'Subtareas',
        'res_model': 'subtask.board',
        'view_mode': 'tree',
        'domain': [('id', 'in', self.subtask_ids.ids)],
        'target': 'new',
    }
    
    @api.depends('subtask_ids', 'subtask_ids.status')
    def _compute_progress(self):
        for task in self:
            completed = task.subtask_ids.filtered(lambda x: x.status == 'done')
            task.completed_subtasks = len(completed)
            task.total_subtasks = len(task.subtask_ids)
            task.progress = (task.completed_subtasks / task.total_subtasks) * 100 if task.total_subtasks > 0 else 0
            
    @api.depends('status')
    def _compute_color_from_state(self):
        for task in self:
            if task.status == 'new':
                task.color = 2  # Amarillo
            elif task.status == 'in_progress':
                task.color = 5  # Naranja
            elif task.status == 'done':
                task.color = 10  # Verde
            elif task.status == 'stuck':
                task.color = 1  # Rojo
            else:
                task.color = 0  # Por defecto

    @api.depends('department_id')
    def _compute_allowed_members(self):
        for task in self:
            task.allowed_member_ids = task.department_id.member_ids

    @api.constrains('person', 'department_id')
    def _check_person_in_department(self):
        for task in self:
            if task.department_id and task.person not in task.department_id.member_ids:
                raise ValidationError(
                    "El empleado asignado no pertenece al departamento seleccionado. "
                    "Miembros válidos: %s" % 
                    ", ".join(task.department_id.member_ids.mapped('name'))
                )

    @api.model
    def create(self, vals):
        task = super().create(vals)
        task._check_person_in_department()
        return task

    def write(self, vals):
        res = super().write(vals)
        self._check_person_in_department()
        return res

    def open_details_form(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Details Board',
            'res_model': 'task.board',
            'res_id': self.id,
            'view_mode': 'form',
            'view_id': self.env.ref('task_planner.activity_planner_details_view_form').id,
            'target': 'current',
        }
    
    def _is_valid_db_identifier(self, name):
        """Valida si el nombre es un identificador válido de columna en PostgreSQL"""
        import re
        return re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', name) is not None
