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
    )

    apply_to_specific_task = fields.Boolean(
        string="Aplicar a tarea específica",
        help="Si está marcado, el campo dinámico se aplicará solo a la tarea seleccionada"
    )
    dynamic_field_list = fields.Many2many(
    'boards.planner',
    string='Campos Dinámicos',
    compute='_compute_dynamic_fields',
    store=False
    )

    sequence = fields.Integer(string='Sequence', default=10)
    drag = fields.Integer()
    files = fields.Many2many('ir.attachment', string="Files")
    name = fields.Char(string="Task", required=True )
    person = fields.Many2one(
        'hr.employee',
        string='Assigned To',
        tracking=True,
        required=True,
        domain="[('id', 'in', allowed_member_ids)]"
    )

    STATES = [
    ('new', 'New'),
    ('in_progress', 'In Progress'),
    ('done', 'Done'),
    ('stuck', 'Stuck'),
    ('view_subtasks', 'View Subtasks')  
    ]

    color = fields.Integer(string='Color Index', compute='_compute_color_from_state', store=True)
    state = fields.Selection(STATES, default="new", string="State")
    subtask_ids = fields.One2many('subtask.board', 'task_id', string='Subtasks')
    task_ids = fields.One2many('task.board', 'department_id', invisible=1, string="Tasks")
    subtasks_count= fields.Integer(
        string="Subtask Count",
        compute='_compute_subtask_count',
        store=True,
        default=0  # Añadir valor por defecto
    )

    allowed_member_ids = fields.Many2many(
        'hr.employee',
        compute='_compute_allowed_members',
        string='Allowed Members'
    )

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

    show_subtasks = fields.Boolean(string="Show Subtasks")
    parent_id = fields.Many2one('task.board', 'Parent Task', index=True, ondelete='cascade')
    child_ids = fields.One2many('task.board', 'parent_id', 'Sub-tasks')
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
    dynamic_fields_data = fields.Text(string='Campos Dinámicos')
    dynamic_field_names = fields.Text(
    string="Campos Dinámicos",
    compute='_compute_dynamic_fields',
    store=False
    )

    dynamic_field_ids = fields.One2many(
    'ir.model.fields', 
    compute='_compute_dynamic_fields',
    string="Campos Dinámicos"
    )
      
    @api.model
    def create(self, vals):
        task = super(TaskBoard, self).create(vals)
        if self.env.context.get('kanban_auto_refresh'):
            return {
                'type': 'ir.actions.client',
                'tag': 'reload',
            }
        return task

    def _compute_dynamic_fields(self):
        for record in self:
            # Obtener todos los campos dinámicos (que empiezan con x_)
            dynamic_fields = self.env['ir.model.fields'].search([
                ('model', '=', self._name),
                ('name', 'like', 'x_%'),
                ('state', '=', 'manual')
            ])
            record.dynamic_field_ids = dynamic_fields

    def action_toggle_subtasks(self):
        for task in self:
            task.show_subtasks = not task.show_subtasks
        return True

    def action_view_subtasks(self):
        self.ensure_one()
        return {
        'name': 'Subtareas',  
        'type': 'ir.actions.act_window',
        'res_model': 'subtask.board', 
        'view_mode': 'tree,form',  
        'views': [(False, 'tree'), (False, 'form')],  
        'domain': [('task_id', '=', self.id)],  
        'context': {'default_task_id': self.id},  
        'target': 'new', 
    }

    def action_close_subtasks(self):
        """
        Acción para cerrar subtareas. Cambia el estado a 'draft' y recarga la vista.
        """
        self.write({'state': 'draft'})  # O el estado normal de tus tareas
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

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
        """Versión final que maneja correctamente el checkbox y agrega como columnas"""
        self.ensure_one()
        
        if not self.dynamic_field_name or not self.dynamic_field_type:
            raise ValidationError("Debe especificar nombre y tipo de campo")
    
        # Generar nombre válido
        field_name = self._generate_valid_field_name(self.dynamic_field_name)
        
        # Crear el campo en el modelo
        self._create_field_in_model(field_name)
        
        # Actualizar vistas según el checkbox
        if self.apply_to_specific_task:
            self._update_kanban_view_for_task(field_name, self.id)
        else:
            self._update_kanban_view_globally(field_name)
        
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

    def _update_kanban_view_globally(self, field_name):
        """Actualiza vista kanban para todas las tareas"""
        field_attrs = {
            'name': field_name,
            'string': self.dynamic_field_label or field_name.replace('_', ' ').title()
        }

        if self.dynamic_field_type == 'selection':
            field_attrs['widget'] = 'selection'
        elif self.dynamic_field_type in ['date', 'datetime']:
            field_attrs['widget'] = self.dynamic_field_type

        arch = f"""
        <data>
            <xpath expr="//div[hasclass('o_kanban_record')]" position="inside">
                <div class="oe_kanban_content" style="margin-top:8px">
                    <field name="{field_name}" {'widget="'+field_attrs['widget']+'"' if 'widget' in field_attrs else ''}/>
                </div>
            </xpath>
        </data>
        """

        self._update_view(
            view_xml_id='task_planner.activity_planner_task_view_kanban',
            view_type='kanban',
            arch=arch,
            view_name=f'{self._name}.kanban.global_inherit_{field_name}'
        )

    def _update_kanban_view_for_task(self, field_name, task_id):
        """Versión corregida que funciona con todos los tipos de campos"""
        self.ensure_one()

        # Configuración del campo según su tipo
        field_attrs = {
            'name': field_name,
            'string': self.dynamic_field_label or field_name.replace('_', ' ').title()
        }

        # Widget especial para ciertos tipos de campo
        if self.dynamic_field_type == 'selection':
            field_attrs['widget'] = 'selection'
        elif self.dynamic_field_type in ['date', 'datetime']:
            field_attrs['widget'] = self.dynamic_field_type

        # Generar el XML de forma segura
        arch = f"""
        <data>
            <xpath expr="//div[hasclass('o_kanban_record')]" position="inside">
                <t t-if="record.id == {task_id}">
                    <div class="oe_kanban_content" style="margin-top:8px">
                        <field name="{field_name}" {'widget="'+field_attrs['widget']+'"' if 'widget' in field_attrs else ''}/>
                    </div>
                </t>
            </xpath>
        </data>
        """

        self._update_view(
            view_xml_id='task_planner.activity_planner_task_view_kanban',
            view_type='kanban',
            arch=arch,
            view_name=f'{self._name}.kanban.task_{task_id}_inherit_{field_name}'
        )

   

    def _update_view(self, view_xml_id, view_type, arch, view_name):
        """Actualiza vista de manera genérica"""
        try:
            base_view = self.env.ref(view_xml_id)
            inherit_view = self.env['ir.ui.view'].search([
                ('name', '=', view_name),
                ('model', '=', self._name)
            ], limit=1)

            if inherit_view:
                inherit_view.write({'arch': arch})
            else:
                self.env['ir.ui.view'].create({
                    'name': view_name,
                    'type': view_type,
                    'model': self._name,
                    'inherit_id': base_view.id,
                    'arch': arch,
                    'active': True
                })

            self.env['ir.ui.view'].clear_caches()
        except Exception as e:
            _logger.error("Error updating view: %s", str(e))
            raise ValidationError("Error al actualizar vista kanban")

    def _safe_cache_cleanup(self):
        """Método mejorado para limpiar caché"""
        try:
            # Limpiar caché de registros
            self.env.registry.clear_cache()

            # Limpiar caché de vistas
            if hasattr(self.env['ir.ui.view'], 'clear_caches'):
                self.env['ir.ui.view'].clear_caches()

            # Recargar definiciones del modelo
            if self._name in self.env.registry:
                model = self.env.registry[self._name]
                model._fields = {}
                model._setup_fields()
                model._setup_complete()

        except Exception as e:
            _logger.warning("Advertencia al limpiar caché: %s", str(e))

    def _create_field_in_model_safe(self, field_name):
        """Versión corregida que incluye el string del campo"""
        try:
            model = self.env['ir.model'].search([('model', '=', self._name)], limit=1)
            if not model:
                raise ValidationError(f"Modelo {self._name} no encontrado")

            field_vals = {
                'name': field_name,
                'model_id': model.id,
                'field_description': self.dynamic_field_label or field_name,  # Asegura que siempre tenga descripción
                'ttype': self.dynamic_field_type,
                'state': 'manual',
                'required': False,
                'readonly': False,
                'index': False,
            }

            if self.dynamic_field_type == 'selection' and self.selection_options:
                selection = []
                for line in self.selection_options.split('\n'):
                    if line.strip() and ':' in line:
                        key, val = map(str.strip, line.split(':', 1))
                        selection.append((key, val))
                field_vals['selection'] = str(selection)

            # Validación adicional para asegurar el string
            if not field_vals.get('field_description'):
                field_vals['field_description'] = field_name.replace('_', ' ').title()

            self.env['ir.model.fields'].sudo().create(field_vals)
            self._add_column_to_table(field_name)

        except Exception as e:
            _logger.error("Error creando campo: %s", str(e))
            raise
        
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
           
            self._update_specific_view(
                view_xml_id='task_planner.activity_planner_task_view_kanban',
              view_type='kanban',
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
                    view_xml_id='task_planner.activity_planner_task_view_kanban',
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

    def _generate_complete_kanban_view(self, base_view, field_name):
        """Regenera la vista kanban manteniendo todos los campos existentes"""
        try:
            # Parsear la vista existente
            doc = etree.fromstring(base_view.arch)

            # Encontrar la tabla y filas
            table = doc.xpath("//table")[0]
            header_row = table.xpath(".//tr[th]")[0]
            data_rows = table.xpath(".//tr[td]")

            # Buscar la posición después del campo "Fecha"
            fecha_th = None
            for idx, th in enumerate(header_row.xpath(".//th")):
                if th.text and "fecha" in th.text.lower():
                    fecha_th = (idx, th)
                    break
                
            # Crear nuevo encabezado
            new_th = etree.Element("th", style="border: 1px solid #dee2e6; background: #f8f9fa;")
            new_th.text = self.dynamic_field_label or field_name.replace('_', ' ').title()

            # Insertar después de "Fecha" o al final si no se encuentra
            if fecha_th:
                idx, th = fecha_th
                th.addnext(new_th)
            else:
                header_row.append(new_th)

            # Añadir celda de datos en cada fila
            for row in data_rows:
                new_td = etree.Element("td", style="border: 1px solid #dee2e6;")
                field = etree.Element("field", name=field_name)

                # Configurar widget según tipo
                if self.dynamic_field_type == 'selection':
                    field.set("widget", "selection")
                elif self.dynamic_field_type in ['date', 'datetime']:
                    field.set("widget", self.dynamic_field_type)

                new_td.append(field)

                # Insertar en la misma posición que el encabezado
                if fecha_th and len(row.xpath(".//td")) > fecha_th[0]:
                    target_td = row.xpath(".//td")[fecha_th[0]]
                    target_td.addnext(new_td)
                else:
                    row.append(new_td)

            return etree.tostring(doc, encoding='unicode')
        except Exception as e:
            _logger.error("Error generando vista kanban: %s", str(e))
            raise ValidationError("Error al actualizar la vista kanban")

    def _update_specific_view(self, view_xml_id, view_type, field_name):
        """Actualiza la vista manteniendo todos los campos existentes"""
        try:
            base_view = self.env.ref(view_xml_id)
            inherit_view_name = f"{self._name}.{view_type}.inherit.{field_name}"

            # Buscar vista heredada existente para este campo
            inherited_view = self.env['ir.ui.view'].search([
                ('name', '=', inherit_view_name),
                ('model', '=', self._name)
            ], limit=1)

            # Generar archivo XML según tipo de vista
            if view_type == 'kanban':
                arch = self._generate_complete_kanban_view(base_view, field_name)
            else:
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

            # Limpiar caché
            self.env['ir.ui.view'].clear_caches()

        except Exception as e:
            _logger.error("Error actualizando vista %s: %s", view_xml_id, str(e))
            raise ValidationError(f"Error al actualizar vista {view_type}")

    def _generate_view_arch_with_field(self, base_view, view_type, field_name):
        """Genera XML para insertar el nuevo campo manteniendo los existentes"""
        position_info = self._get_best_position_for_field(base_view, view_type)

        field_attrs = {
            'name': field_name,
            'string': self.dynamic_field_label or field_name.replace('_', ' ').title(),
            'optional': 'show'
        }
        # Configurar widgets especiales
        if self.dynamic_field_type == 'selection':
            field_attrs['widget'] = 'selection'
        elif self.dynamic_field_type in ['date', 'datetime']:
            field_attrs['widget'] = self.dynamic_field_type
        return f"""
        <data>
            <xpath expr="{position_info['xpath']}" position="{position_info['position']}">
                <field {' '.join([f'{k}="{v}"' for k, v in field_attrs.items()])}/>
            </xpath>
        </data>
        """

    def _get_best_position_for_field(self, base_view, view_type):
        """Encuentra la mejor posición para insertar el nuevo campo"""
        try:
            doc = etree.fromstring(base_view.arch)
            
            if view_type == 'form':
                # Intentar encontrar el campo "fecha" para insertar después
                fecha_field = doc.xpath("//field[contains(translate(@name, 'FECH', 'fech'), 'fecha')]")
                if fecha_field:
                    return {
                        'xpath': f"//field[@name='{fecha_field[0].get('name')}']",
                        'position': 'after'
                    }
                
                # Si no hay campo fecha, insertar después del último campo
                last_field = doc.xpath("(//field[not(ancestor::field)])[last()]")
                if last_field:
                    return {
                        'xpath': f"//field[@name='{last_field[0].get('name')}']",
                        'position': 'after'
                    }
                
                # Insertar en el sheet si no hay campos
                sheet = doc.xpath("//sheet")[0] if doc.xpath("//sheet") else doc
                return {
                    'xpath': "//sheet" if doc.xpath("//sheet") else "/*",
                    'position': 'inside'
                }
                  
            elif view_type == 'tree':
                # Buscar campo fecha para insertar después
                fecha_field = doc.xpath("//field[contains(translate(@name, 'FECH', 'fech'), 'fecha')]")
                if fecha_field:
                    return {
                        'xpath': f"//field[@name='{fecha_field[0].get('name')}']",
                        'position': 'after'
                    }
                
                # Insertar después del último campo visible
                last_field = doc.xpath("(//field[not(@invisible)])[last()]") or doc.xpath("(//field)[last()]")
                if last_field:
                    return {
                        'xpath': f"//field[@name='{last_field[0].get('name')}']",
                        'position': 'after'
                    }
                
            # Posición por defecto
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
        """Crea el campo dinámico en el modelo (versión corregida)"""
        if not self.dynamic_field_type:
            raise ValidationError("Debe seleccionar un tipo de campo.")
        # Mapeo de tipos de campo a configuraciones adicionales
        field_type = self.dynamic_field_type
        field_vals = {
            'name': field_name,
            'field_description': self.dynamic_field_label or field_name.replace('_', ' ').title(),
            'ttype': field_type,
            'state': 'manual',
            'required': False,
            'readonly': False,
            'index': False,
        }

        # Manejar campos de selección
        if field_type == 'selection':
            if not self.selection_options:
                raise ValidationError("Debe proporcionar opciones para el campo de selección.")

            selection = []
            for line in self.selection_options.split('\n'):
                line = line.strip()
                if line and ':' in line:
                    key, val = map(str.strip, line.split(':', 1))
                    selection.append((key, val))

            if not selection:
                raise ValidationError("Debe proporcionar al menos una opción válida en formato clave:valor")

            field_vals['selection'] = str(selection)

        # Buscar el modelo
        model = self.env['ir.model'].search([('model', '=', self._name)], limit=1)
        if not model:
            raise ValidationError(f"Modelo {self._name} no encontrado")

        field_vals['model_id'] = model.id

        try:
            # Crear el campo técnico
            self.env['ir.model.fields'].sudo().create(field_vals)

            # Añadir la columna a la tabla
            self._add_column_to_table(field_name)

            # Limpiar caché para que el campo esté disponible inmediatamente
            self._safe_cache_cleanup()

        except Exception as e:
            _logger.error("Error creando campo: %s", str(e))
            raise ValidationError(f"Error al crear el campo: {str(e)}")

    def is_dynamic_field_for_task(self, field_name):
        """Verifica si un campo dinámico está asociado específicamente a esta tarea"""
        self.ensure_one()

        if not self.dynamic_fields_data:
            return False

        try:
            dynamic_data = json.loads(self.dynamic_fields_data)
            return field_name in dynamic_data
        except (json.JSONDecodeError, TypeError):
            _logger.warning("Error al parsear dynamic_fields_data en tarea %s", self.id)
            return False
    def _generate_view_arch_with_field(self, base_view, view_type, field_name):
        """Genera el XML para la vista con el nuevo campo"""
        # Determinar la mejor posición para insertar el campo
        position_info = self._get_best_position_for_field(base_view, view_type)
        if self.apply_to_specific_task and not self.is_dynamic_field_for_task(field_name):
            return "<data/>" 
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
  

    def _format_field_attrs(self, attrs):
        """Formatea atributos para XML de manera segura"""
        safe_attrs = {}
        for k, v in attrs.items():
            if v is not None:
                safe_attrs[k] = v
        return ' '.join([f'{k}="{v}"' for k, v in safe_attrs.items()])

    def _generate_safe_view_arch(self, view_type, field_name, base_view=None):
        """
        Genera XML seguro para la vista
        Versión simplificada y unificada para todos los tipos de vista
        """
        field_attrs = {
            'name': field_name,
            'string': self.dynamic_field_label or field_name.replace('_', ' ').title(),
        }

        # Configura widgets especiales según el tipo de campo
        if self.dynamic_field_type == 'selection':
            field_attrs['widget'] = 'selection'
        elif self.dynamic_field_type in ['date', 'datetime']:
            field_attrs['widget'] = self.dynamic_field_type

        # Estructura básica para vista kanban
        if view_type == 'kanban':
            return f"""
            <data>
                <xpath expr="//templates//div[hasclass('o_kanban_record')]//field[@name='display_name']" position="after">
                    <div class="oe_kanban_content">
                        <field {self._format_field_attrs(field_attrs)}/>
                    </div>
                </xpath>
            </data>
            """
        # Estructura para vista form
        elif view_type == 'form':
            return f"""
            <data>
                <xpath expr="//sheet" position="inside">
                    <group>
                        <field {self._format_field_attrs(field_attrs)}/>
                    </group>
                </xpath>
            </data>
            """
        # Estructura para vista tree
        elif view_type == 'tree':
            return f"""
            <data>
                <xpath expr="//tree" position="inside">
                    <field {self._format_field_attrs(field_attrs)}/>
                </xpath>
            </data>
            """
        # Estructura por defecto
        else:
            return f"""
            <data>
                <field {self._format_field_attrs(field_attrs)} position="attributes">
                    <attribute name="invisible">0</attribute>
                </field>
            </data>
            """

    def _format_field_attrs(self, attrs):
        """Formatea atributos para XML de manera segura"""
        safe_attrs = {}
        for k, v in attrs.items():
            if v is not None:
                safe_attrs[k] = v
        return ' '.join([f'{k}="{v}"' for k, v in safe_attrs.items()])

    def _update_specific_view(self, view_xml_id, view_type, field_name):
        """Versión corregida para actualizar vistas"""
        try:
            base_view = self.env.ref(view_xml_id)
            if not base_view:
                _logger.warning(f"Vista {view_xml_id} no encontrada")
                return False

            # Generar archivo XML según tipo de vista
            if view_type == 'kanban':
                arch = self._generate_kanban_view_arch(field_name)
            else:
                arch = self._generate_view_arch_with_field(
                    base_view=base_view,
                    view_type=view_type,
                    field_name=field_name
                )

            inherit_view_name = f"{self._name}.{view_type}.inherit.{field_name}"
            inherit_view = self.env['ir.ui.view'].search([
                ('name', '=', inherit_view_name),
                ('model', '=', self._name)
            ], limit=1)

            if inherit_view:
                inherit_view.write({'arch': arch})
            else:
                self.env['ir.ui.view'].create({
                    'name': inherit_view_name,
                    'type': view_type,
                    'model': self._name,
                    'inherit_id': base_view.id,
                    'arch': arch,
                    'active': True
                })

            self.env['ir.ui.view'].clear_caches()
            return True

        except Exception as e:
            _logger.error(f"Error actualizando vista {view_xml_id}: {str(e)}")
            raise ValidationError(f"Error al actualizar vista {view_type}: {str(e)}")

    def _generate_kanban_view_arch(self, field_name, specific_task=False, task_id=None):
        """Genera XML para la vista kanban como columnas"""
        field_attrs = {
            'name': field_name,
            'string': self.dynamic_field_label or field_name.replace('_', ' ').title()
        }

        # Configurar widget según tipo de campo
        if self.dynamic_field_type == 'selection':
            field_attrs['widget'] = 'selection'
        elif self.dynamic_field_type in ['date', 'datetime']:
            field_attrs['widget'] = self.dynamic_field_type

        if specific_task and task_id:
            # Versión para tarea específica
            return f"""
            <data>
                <xpath expr="//div[hasclass('o_kanban_record')]" position="inside">
                    <div class="oe_kanban_global_click">
                        <div class="row" t-if="record.id == {task_id}">
                            <div class="col-3">
                                <field {self._format_field_attrs(field_attrs)}/>
                            </div>
                        </div>
                    </div>
                </xpath>
            </data>
            """
        else:
            # Versión global
            return f"""
            <data>
                <xpath expr="//div[hasclass('o_kanban_record')]" position="inside">
                    <div class="oe_kanban_global_click">
                        <div class="row">
                            <div class="col-3">
                                <field {self._format_field_attrs(field_attrs)}/>
                            </div>
                        </div>
                    </div>
                </xpath>
            </data>
            """
    def _update_kanban_view(self, field_name):
        """Actualiza la vista kanban de manera segura"""
        try:
            kanban_arch = self._generate_kanban_view_arch(field_name)
            base_view = self.env.ref('task_planner.activity_planner_task_view_kanban')

            inherit_view = self.env['ir.ui.view'].search([
                ('name', '=', f'{self._name}.kanban.inherit.{field_name}'),
                ('model', '=', self._name)
            ], limit=1)

            if inherit_view:
                inherit_view.write({'arch': kanban_arch})
            else:
                self.env['ir.ui.view'].create({
                    'name': f'{self._name}.kanban.inherit.{field_name}',
                    'type': 'kanban',
                    'model': self._name,
                    'inherit_id': base_view.id,
                    'arch': kanban_arch,
                    'active': True
                })

            self.env['ir.ui.view'].clear_caches()
        except Exception as e:
            _logger.error("Error updating kanban view: %s", str(e))
            raise ValidationError("Error al actualizar vista kanban")

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

    def _reload_model_definition(self):
        """Recarga la definición del modelo actual desde la base de datos."""
        if isinstance(self.env[self._name], BaseModel):
           self.env[self._name]._setup_fields()
           self.env[self._name]._setup_complete()

    def _add_column_to_table(self, field_name):
        """Añade la columna a la tabla en la base de datos de manera segura"""
        # Mapeo de tipos de campo de Odoo a tipos de PostgreSQL
        type_mapping = {
            'char': 'VARCHAR(255)',
            'integer': 'INTEGER',
            'float': 'NUMERIC',
            'boolean': 'BOOLEAN',
            'selection': 'VARCHAR(255)',
            'date': 'DATE',
            'datetime': 'TIMESTAMP',
            'text': 'TEXT'
        }

        column_type = type_mapping.get(self.dynamic_field_type, 'VARCHAR(255)')

        try:
            # Verificar si la columna ya existe
            self.env.cr.execute(f"""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = '{self._table}' 
                AND column_name = '{field_name}'
            """)

            if not self.env.cr.fetchone():
                # La columna no existe, crearla
                query = f"""
                ALTER TABLE {self._table} 
                ADD COLUMN {field_name} {column_type}
                """
                self.env.cr.execute(query)

                # Hacer commit explícito para la operación DDL
                self.env.cr.commit()

        except Exception as e:
            _logger.error("Error añadiendo columna: %s", str(e))
            self.env.cr.rollback()
            raise ValidationError(f"Error técnico al crear el campo en la base de datos: {str(e)}")

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
    
    @api.depends('subtask_ids.state')
    def _compute_progress(self):
        for task in self:
            subtasks = task.subtask_ids
            total = len(subtasks)
            done = len(subtasks.filtered(lambda x: x.state == 'done'))
            task.total_subtasks = total
            task.completed_subtasks = done
            # Calcular progreso (0-100)
            progress = total and (done * 100.0 / total) or 0
            task.progress = progress
            # Cambiar estado automáticamente cuando progreso es 100%
            if progress >= 100 and task.state != 'done':
                task.state = 'done'
            elif progress > 0 and progress < 100 and task.state != 'in_progress':
                task.state = 'in_progress'
            
    @api.depends('state')
    def _compute_color_from_state(self):
        for task in self:
            if task.state == 'new':
                task.color = 2  # Amarillo
            elif task.state == 'in_progress':
                task.color = 5  # Naranja
            elif task.state == 'done':
                task.color = 10  # Verde
            elif task.state == 'stuck':
                task.color = 1  # Rojo
            elif task.state == 'view_subtasks':
                task.color = 4   
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