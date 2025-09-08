from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import logging
import re
import json
from datetime import datetime
from .boards import STATES

_logger = logging.getLogger(__name__)

class SubtaskActivity(models.Model):
    _name = 'subtask.activity'
    _description = 'Actividad Interna de Subtarea'
    _inherit = ['mail.activity.mixin']
    
    name = fields.Char(string='Nombre de la Subtarea', required=True)
    date_deadline = fields.Date(string='Fecha')
    done = fields.Boolean(string='Completado')
    subtask_id = fields.Many2one('subtask.board', string='Subtarea', ondelete='cascade', required=True)
    person = fields.Many2one('hr.employee', string='Responsable')
    allowed_member_ids = fields.Many2many('hr.employee', string='Responsables', readonly=True)
    task_board_id = fields.Many2one('task.board', string='Grupo', related='subtask_id.task_id', store=True)
    state = fields.Selection(STATES, default="new", string="Estado")
    
    # Campos para almacenar la información del campo dinámico
    dynamic_field_name = fields.Char(string='Nombre Técnico del Campo')
    dynamic_field_label = fields.Char(string='Etiqueta del Campo')
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
        required=True,
        default='char' 
    )
    
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
   
    default_value = fields.Text(string='Valor por Defecto')
   
    sequence_number_id = fields.Integer(
        string='Número de secuencia',
        readonly=True,
        copy=False,
        default=0
    )

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
                
    @api.model_create_multi
    def create(self, vals_list):
        # Buscar el MÁXIMO sequence_number_id existente
        max_record = self.search([], order='sequence_number_id desc', limit=1)
        max_sequence = max_record.sequence_number_id if max_record else 0
        
        # Si no hay registros O el máximo es 0, empezar desde 1
        if max_sequence == 0:
            if vals_list:
                vals_list[0]['sequence_number_id'] = 1
                # Asignar secuencia a los demás registros
                if len(vals_list) > 1:
                    for i, vals in enumerate(vals_list[1:], start=2):
                        vals['sequence_number_id'] = i
        else:
            # Continuar desde el máximo existente + 1
            for vals in vals_list:
                max_sequence += 1
                vals['sequence_number_id'] = max_sequence
    
        return super(SubtaskActivity, self).create(vals_list)
    
    def action_open_delete_field_wizard(self):
        self.ensure_one()
        return {
            'name': _('Eliminar Campo Dinámico de Actividad'),
            'type': 'ir.actions.act_window',
            'res_model': 'delete.field.subtask.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_activity_id': self.id,
            }
        }
    
    def open_dynamic_field_wizard(self):
        """Abre el wizard para crear campos dinámicos"""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Crear Campo Dinámico',
            'res_model': 'add.field.subtask.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_activity_id': self.id,
                'default_task_board_id': self.task_board_id.id,
            }
        }

    def action_create_dynamic_field(self):
        """Crea el campo dinámico en la actividad"""
        self.ensure_one()
        
        if not self.dynamic_field_name or not self.dynamic_field_type:
            raise UserError(_("¡Error! El nombre técnico y tipo de campo son obligatorios"))
        
        # Validación especial para campos de selección
        if self.dynamic_field_type == 'selection' and not self.selection_options:
            raise UserError(_("¡Error! Debe ingresar opciones para campos de selección"))
        
        # Generar nombre técnico con prefijo
        field_name = self._generate_field_name()
        
        # Verificar si el campo ya existe
        if self._field_exists(field_name):
            raise UserError(_("¡Error! El campo %s ya existe") % field_name)
        
        # Preparar opciones de selección si es necesario
        selection_values = False
        if self.dynamic_field_type == 'selection' and self.selection_options:
            options = []
            for line in self.selection_options.split('\n'):
                line = line.strip()
                if line and ':' in line:
                    key, val = line.split(':', 1)
                    options.append((key.strip(), val.strip()))
            if options:
                selection_values = str(options)
        
        # Crear el campo en la base de datos
        self._create_field_in_db(field_name)
        
        # Crear registro en ir.model.fields
        self._create_ir_model_field(field_name, selection_values)
        
        # Actualizar vistas
        self._update_views(field_name)
        
        # Forzar actualización del modelo
        self._reload_model()
        
        # Almacenar metadatos
        self._store_field_metadata(field_name, selection_values)
        
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

    def _generate_field_name(self):
        """Genera nombre técnico válido con prefijo x_"""
        clean_name = re.sub(r'[^a-zA-Z0-9_]', '', self.dynamic_field_name.strip().lower().replace(' ', '_'))
        return f'x_{clean_name}' if not clean_name.startswith('x_') else clean_name

    def _field_exists(self, field_name):
        """Verifica si el campo ya existe"""
        return bool(self.env['ir.model.fields'].search([
            ('model', '=', 'subtask.activity'),
            ('name', '=', field_name)
        ]))

    def _create_field_in_db(self, field_name):
        """Crea la columna física en la base de datos"""
        column_type = {
            'char': 'VARCHAR(255)',
            'integer': 'INTEGER',
            'float': 'NUMERIC',
            'boolean': 'BOOLEAN',
            'date': 'DATE',
            'datetime': 'TIMESTAMP',
            'selection': 'VARCHAR(255)'
        }.get(self.dynamic_field_type)
        
        if not column_type:
            raise UserError(_("Tipo de campo no válido: %s") % self.dynamic_field_type)
        
        try:
            self.env.cr.execute(f"""
                ALTER TABLE subtask_activity 
                ADD COLUMN {field_name} {column_type}
            """)
            _logger.info("Columna %s creada en BD", field_name)
        except Exception as e:
            _logger.error("Error creando columna: %s", str(e))
            if "already exists" in str(e):
                raise UserError(_("El campo '%s' ya existe en la base de datos.") % field_name)
            else:
                raise UserError(_("Error técnico al crear el campo. Consulte los logs."))

    def _create_ir_model_field(self, field_name, selection_values=False):
        """Crea el registro en ir.model.fields"""
        model_id = self.env['ir.model'].search([('model', '=', 'subtask.activity')], limit=1)
        if not model_id:
            raise UserError(_("Modelo subtask.activity no encontrado"))
        
        field_vals = {
            'name': field_name,
            'model_id': model_id.id,
            'field_description': self.dynamic_field_label or self.dynamic_field_name,
            'ttype': self.dynamic_field_type,
            'state': 'manual',
            'store': True,
        }
        
        # Manejar campos de selección
        if self.dynamic_field_type == 'selection' and selection_values:
            field_vals['selection'] = selection_values
        
        try:
            self.env['ir.model.fields'].create(field_vals)
            _logger.info("Campo %s registrado en ir.model.fields", field_name)
        except Exception as e:
            _logger.error("Error registrando campo: %s", str(e))
            raise UserError(_("Error al registrar el campo. Consulte los logs."))

    def _store_field_metadata(self, field_name, selection_values=False):
        """Store field configuration in JSON con manejo de datetime"""
        try:
            # Convertir datetime a string ISO para serialización JSON
            created_at = fields.Datetime.now()
            if hasattr(created_at, 'isoformat'):
                created_at = created_at.isoformat()
            
            field_data = {
                'name': field_name,
                'label': self.dynamic_field_label,
                'type': self.dynamic_field_type,
                'created_at': created_at,
                'created_by': self.env.user.id,
            }
            
            # Añadir opciones de selección si es el caso
            if self.dynamic_field_type == 'selection' and selection_values:
                # Convertir de string a lista si es necesario
                if isinstance(selection_values, str):
                    try:
                        selection_values = eval(selection_values)
                    except:
                        selection_values = []
                
                field_data['options'] = selection_values
            
            # Manejar datos existentes
            current_data = {}
            if self.dynamic_fields_data:
                try:
                    current_data = json.loads(self.dynamic_fields_data)
                except json.JSONDecodeError:
                    current_data = {}
                    _logger.warning("Invalid JSON in dynamic_fields_data, resetting")
            
            # Actualizar con nuevos datos
            current_data[field_name] = field_data
            
            # Serializar usando el método seguro
            self.dynamic_fields_data = json.dumps(current_data, default=str)
            
        except Exception as e:
            _logger.error("Metadata storage failed: %s", str(e))
            raise UserError(_("Error storing field metadata: %s") % str(e))

    def _update_views(self, field_name):
        """Actualiza las vistas de subtask.activity para incluir el nuevo campo"""
        try:
            field_label = self.dynamic_field_label or self.dynamic_field_name

            # 1. Vista Form principal - activity_planner_subtask_form (para el árbol de líneas de actividad)
            planner_form_view = self.env.ref('task_planner.activity_planner_subtask_form')
            if planner_form_view:
                # XPath CORREGIDO - apuntar al árbol dentro del campo one2many
                arch_planner_form = f"""
                    <data>
                        <xpath expr="//field[@name='activity_line_ids']/tree/field[@name='person']" position="after">
                            <field name="{field_name}" string="{field_label}"/>
                        </xpath>
                    </data>
                    """
                    
                existing_planner_view = self.env['ir.ui.view'].search([
                    ('name', '=', f'subtask.planner.form.dynamic.{field_name}'),
                    ('model', '=', 'subtask.board')
                ])
                if existing_planner_view:
                    existing_planner_view.unlink()

                self.env['ir.ui.view'].create({
                    'name': f'subtask.planner.form.dynamic.{field_name}',
                    'model': 'subtask.board',
                    'inherit_id': planner_form_view.id,
                    'arch': arch_planner_form,
                    'type': 'form',
                    'priority': 100,
                })
                _logger.info("✅ Vista planner form (árbol) actualizada con campo %s", field_name)
    
            # 2. Vista Form de subtask.activity - view_subtask_activity_form
            form_view_2 = self.env.ref('task_planner.view_subtask_activity_form', raise_if_not_found=False)
            if form_view_2:
                arch_form_2 = f"""
                <data>
                    <xpath expr="//field[@name='person']" position="after">
                        <field name="{field_name}" string="{field_label}"/>
                    </xpath>
                </data>
                """
                existing_view_2 = self.env['ir.ui.view'].search([
                    ('name', '=', f'subtask.activity.form.dynamic.{field_name}'),
                    ('model', '=', 'subtask.activity')
                ])
                if existing_view_2:
                    existing_view_2.unlink()
    
                self.env['ir.ui.view'].create({
                    'name': f'subtask.activity.form.dynamic.{field_name}',
                    'model': 'subtask.activity',
                    'inherit_id': form_view_2.id,
                    'arch': arch_form_2,
                    'type': 'form',
                    'priority': 100,
                })
                _logger.info("✅ Vista form de subtask.activity actualizada con campo %s", field_name)
    
            # 3. Vista Tree - view_subtask_activity_tree (para el modelo subtask.activity)
            tree_view = self.env.ref('task_planner.view_subtask_activity_tree', raise_if_not_found=False)
            if tree_view:
                arch_tree = f"""
                <data>
                    <xpath expr="//field[@name='person']" position="after">
                        <field name="{field_name}" string="{field_label}"/>
                    </xpath>
                </data>
                """
                existing_view = self.env['ir.ui.view'].search([
                    ('name', '=', f'subtask.activity.tree.dynamic.{field_name}'),
                    ('model', '=', 'subtask.activity')
                ])
                if existing_view:
                    existing_view.unlink()
    
                self.env['ir.ui.view'].create({
                    'name': f'subtask.activity.tree.dynamic.{field_name}',
                    'model': 'subtask.activity',
                    'inherit_id': tree_view.id,
                    'arch': arch_tree,
                    'type': 'tree',
                    'priority': 100,
                })
                _logger.info("✅ Vista tree de subtask.activity actualizada con campo %s", field_name)
    
        except Exception as e:
            _logger.error("❌ Error actualizando vistas: %s", str(e))
            raise UserError(_("Error al actualizar vistas. Consulte los logs."))

    def _reload_model(self):
        """Fuerza la recarga del modelo en el registro"""
        try:
            # Limpiar todas las cachés
            self.env.registry.clear_cache()
            self.env['ir.model'].clear_caches()
            self.env['ir.model.fields'].clear_caches()
            self.env['ir.ui.view'].clear_caches()
            
            # Recargar el modelo
            if hasattr(self.env.registry, 'setup_models'):
                self.env.registry.setup_models(self.env.cr)
                
            # Forzar recarga de vistas
            self.env['ir.ui.view']._validate_cache()
            
        except Exception as e:
            _logger.error("Error en recarga de modelo: %s", str(e))

    @api.model
    def fields_view_get(self, view_id=None, view_type='form', toolbar=False, submenu=False):
        """Override para asegurar que los campos dinámicos aparezcan en las vistas"""
        res = super(SubtaskActivity, self).fields_view_get(
            view_id=view_id, view_type=view_type, toolbar=toolbar, submenu=submenu)
        
        try:
            # Buscar campos dinámicos
            dynamic_fields = self.env['ir.model.fields'].search([
                ('model', '=', 'subtask.activity'),
                ('name', 'like', 'x_%'),
                ('state', '=', 'manual')
            ])
            
            if dynamic_fields:
                doc = etree.XML(res['arch'])
                
                # Para vista form
                if view_type == 'form':
                    # Buscar el campo 'person' para insertar después
                    person_fields = doc.xpath("//field[@name='person']")
                    if person_fields:
                        person_field = person_fields[0]
                        for field in dynamic_fields:
                            # Verificar si el campo ya existe en la vista
                            existing_fields = doc.xpath(f"//field[@name='{field.name}']")
                            if not existing_fields:
                                field_elem = etree.Element('field', {
                                    'name': field.name,
                                    'string': field.field_description,
                                })
                                person_field.addnext(field_elem)
                
                # Para vista tree
                elif view_type == 'tree':
                    # Buscar el campo 'person' para insertar después
                    person_fields = doc.xpath("//field[@name='person']")
                    if person_fields:
                        person_field = person_fields[0]
                        for field in dynamic_fields:
                            # Verificar si el campo ya existe en la vista
                            existing_fields = doc.xpath(f"//field[@name='{field.name}']")
                            if not existing_fields:
                                field_elem = etree.Element('field', {
                                    'name': field.name,
                                    'string': field.field_description,
                                })
                                person_field.addnext(field_elem)
                
                res['arch'] = etree.tostring(doc, encoding='unicode')
                
        except Exception as e:
            _logger.error("Error en fields_view_get: %s", str(e))
        
        return res