from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import re
import logging
import json
from datetime import datetime

_logger = logging.getLogger(__name__)

class AddFieldSubtaskWizard(models.TransientModel):
    _name = 'add.field.subtask.wizard'
    _description = 'Asistente para crear campos dinámicos en actividades'

    # Campos del wizard
    field_name = fields.Char(
        string="Nombre Técnico para Campo", 
        required=True, 
        help="Puede usar cualquier nombre. Ej: mi_campo_123, campo2024, etc."
    )
    field_label = fields.Char(string="Etiqueta Visible para Campo", required=True)
    field_type = fields.Selection([  # Cambiado de dynamic_field_type a field_type
        ('char', 'Texto'),
        ('integer', 'Entero'),
        ('float', 'Decimal'),
        ('date', 'Fecha'),
        ('datetime', 'Fecha/Hora'),
        ('boolean', 'Booleano'),
        ('selection', 'Selección')
        ],
        string="Tipo de Campo",
        required=True,
        default='char' 
    )
    
    # Campos para manejar opciones de selección
    selection_option_count = fields.Integer(
        string="Número de Opciones",
        default=0,
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
    
    # Campo que apunta a subtask.board
    subtask_id = fields.Many2one(
        'subtask.board',
        string="Subtarea Relacionada para Campo",
        required=True,
        default=lambda self: self._default_subtask_id()
    )

    # Campo computado para mostrar el nombre de la subtarea
    subtask_name = fields.Char(
        string="Nombre de Subtarea para Campo",
        compute='_compute_subtask_name',
        readonly=True
    )
    
    default_value = fields.Text(string="Valor por Defecto para Campo")
    field_info = fields.Text(string="Información del Campo", readonly=True)

    @api.depends('field_type')
    def _compute_selection_option_count(self):
        """Calcula el número de opciones a mostrar basado en el tipo de campo"""
        for wizard in self:
            if wizard.field_type == 'selection':
                # Si es tipo selección, mostrar al menos 1 opción
                if wizard.selection_option_count < 1:
                    wizard.selection_option_count = 1
            else:
                # Para otros tipos, no mostrar opciones
                wizard.selection_option_count = 0

    @api.onchange('field_type')
    def _onchange_field_type(self):
        """Maneja el cambio en el tipo de campo"""
        if self.field_type != 'selection':
            self.selection_option_count = 0

    def action_add_selection_option(self):
        """Añade una nueva opción al campo de selección"""
        self.ensure_one()
        if self.field_type != 'selection':
            raise UserError(_("Solo puede agregar opciones a campos de tipo selección"))
        
        if self.selection_option_count < 20:  # Aumentado a 20 opciones máximas
            self.selection_option_count += 1
        else:
            raise UserError(_("Máximo 20 opciones permitidas"))
        
        return {
            'type': 'ir.actions.act_window',
            'view_mode': 'form',
            'res_id': self.id,
            'res_model': self._name,
            'target': 'new',
            'context': self.env.context,
        }

    @api.model
    def _default_subtask_id(self):
        """Obtiene la subtarea del contexto"""
        return self.env.context.get('active_id')

    @api.depends('subtask_id')
    def _compute_subtask_name(self):
        """Calcula el nombre de la subtarea"""
        for record in self:
            record.subtask_name = record.subtask_id.name if record.subtask_id else False

    def action_create_dynamic_field(self):
        """Crea el campo dinámico en las actividades de la subtarea"""
        self.ensure_one()

        _logger.info("✅ Wizard ejecutado para subtask.board ID: %s", self.subtask_id.id)
        _logger.info("✅ Nombre de Subtarea: %s", self.subtask_id.name)

        # Validaciones adicionales
        if self.field_type == 'selection' and self.selection_option_count < 1:
            raise UserError(_("¡Error! Debe ingresar al menos una opción para campos de selección"))

        # Generar nombre técnico con prefijo
        field_name = self._generate_field_name()

        _logger.info("Campo a crear: %s en subtask.activity", field_name)

        # Verificar si el campo ya existe ANTES de intentar crearlo
        if self._field_already_exists(field_name):
            raise UserError(_("❌ El campo '%s' ya existe en las actividades. Por favor, use un nombre diferente.") % field_name)

        # Preparar opciones de selección si es necesario
        selection_values = False
        if self.field_type == 'selection':
            options = []
            for i in range(1, self.selection_option_count + 1):
                option_value = getattr(self, f'selection_option_{i}', False)
                if option_value and option_value.strip():
                    # Usar el mismo valor para clave y etiqueta si no se especifica separador
                    if ':' in option_value:
                        key, val = option_value.split(':', 1)
                        options.append((key.strip(), val.strip()))
                    else:
                        options.append((option_value.strip(), option_value.strip()))
            
            if not options:
                raise UserError(_("Debe ingresar al menos una opción válida para el campo de selección"))
                
            selection_values = str(options)

        try:
            # 1. Crear columna en la base de datos
            self._create_column_in_db(field_name)

            # 2. Registrar el campo en ir.model.fields
            self._register_field_in_ir(field_name, selection_values)

            # 3. Actualizar vistas
            self._update_views(field_name)

            # 4. Limpiar cachés
            self._safe_cache_clear()

            # 5. Almacenar metadatos en la subtarea relacionada
            self._store_field_metadata(field_name, selection_values)

            _logger.info("✅ Campo %s creado exitosamente para actividades de la subtarea %s", 
                        field_name, self.subtask_id.name)

            # 6. Recargar la página automáticamente
            return {
                'type': 'ir.actions.client',
                'tag': 'reload',
            }

        except Exception as e:
            _logger.error("❌ Error creando campo: %s", str(e))
            # Revertir cambios si hay error
            try:
                self.env.cr.execute(f"ALTER TABLE subtask_activity DROP COLUMN IF EXISTS {field_name}")
                
                # Eliminar registro en ir.model.fields si se creó
                field_record = self.env['ir.model.fields'].search([
                    ('model', '=', 'subtask.activity'),
                    ('name', '=', field_name)
                ], limit=1)
                if field_record:
                    field_record.unlink()
                    
                # Eliminar vistas creadas
                views = self.env['ir.ui.view'].search([
                    ('name', 'ilike', f'subtask.activity.{field_name}'),
                    ('model', '=', 'subtask.activity')
                ])
                views.unlink()
                
            except Exception as revert_error:
                _logger.warning("⚠️ Error al revertir cambios: %s", str(revert_error))
            
            raise UserError(_("Error al crear campo: %s") % str(e))

    def _store_field_metadata(self, field_name, selection_values=False):
        """Store field configuration in JSON con manejo de datetime"""
        try:
            # Convertir datetime a string ISO para serialización JSON
            created_at = fields.Datetime.now()
            if hasattr(created_at, 'isoformat'):
                created_at = created_at.isoformat()
            
            field_data = {
                'name': field_name,
                'label': self.field_label,
                'type': self.field_type,
                'created_at': created_at,
                'created_by': self.env.user.id,
            }
            
            # Añadir opciones de selección si es el caso
            if self.field_type == 'selection' and selection_values:
                # Convertir de string a lista si es necesario
                if isinstance(selection_values, str):
                    try:
                        selection_values = eval(selection_values)
                    except:
                        selection_values = []
                
                field_data['options'] = selection_values
            
            # Obtener o crear datos existentes
            current_data = {}
            if self.subtask_id.dynamic_fields_data:
                try:
                    current_data = json.loads(self.subtask_id.dynamic_fields_data)
                except json.JSONDecodeError:
                    current_data = {}
                    _logger.warning("Invalid JSON in dynamic_fields_data, resetting")
            
            # Actualizar con nuevos datos
            current_data[field_name] = field_data
            
            # Serializar usando el método seguro
            self.subtask_id.dynamic_fields_data = json.dumps(current_data, default=str)
            
        except Exception as e:
            _logger.error("Metadata storage failed: %s", str(e))
            raise UserError(_("Error storing field metadata: %s") % str(e))

    def _field_already_exists(self, field_name):
        """Verifica si el campo ya existe en la base de datos o en ir.model.fields"""
        # Verificar en la base de datos
        if self._field_already_exists_in_db(field_name):
            return True
        
        # Verificar en ir.model.fields
        field_record = self.env['ir.model.fields'].search([
            ('model', '=', 'subtask.activity'),
            ('name', '=', field_name)
        ], limit=1)
        
        return bool(field_record)

    def _field_already_exists_in_db(self, field_name):
        """Verifica si la columna ya existe en la tabla de la base de datos"""
        try:
            self.env.cr.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'subtask_activity' 
                AND column_name = %s
            """, (field_name,))
            return bool(self.env.cr.fetchone())
        except Exception as e:
            _logger.warning("⚠️ Error al verificar columna en BD: %s", str(e))
            return False

    def _generate_field_name(self):
        """Genera nombre técnico válido con prefijo x_"""
        # Convertir a minúsculas y reemplazar espacios con guiones bajos
        clean_name = self.field_name.strip().lower().replace(' ', '_')
        
        # Reemplazar caracteres especiales con guiones bajos
        clean_name = re.sub(r'[^a-zA-Z0-9_]', '_', clean_name)
        
        # Asegurar que no comience con número
        if clean_name and clean_name[0].isdigit():
            clean_name = 'x_' + clean_name
        # Agregar prefijo x_ si no lo tiene
        elif not clean_name.startswith('x_'):
            clean_name = 'x_' + clean_name
            
        return clean_name

    def _create_column_in_db(self, field_name):
        """Crea la columna física en la base de datos de subtask.activity"""
        column_type = {
            'char': 'VARCHAR(255)',
            'integer': 'INTEGER',
            'float': 'NUMERIC(16,2)',
            'boolean': 'BOOLEAN',
            'date': 'DATE',
            'datetime': 'TIMESTAMP',
            'selection': 'VARCHAR(255)'
        }.get(self.field_type)
        
        if not column_type:
            raise UserError(_("Tipo de campo no válido: %s") % self.field_type)
        
        try:
            query = f"""
                ALTER TABLE subtask_activity 
                ADD COLUMN {field_name} {column_type}
            """
            self.env.cr.execute(query)
            _logger.info("✅ Columna %s creada en tabla subtask_activity", field_name)
            
        except Exception as e:
            _logger.error("❌ Error creando columna: %s", str(e))
            if "already exists" in str(e):
                raise UserError(_("El campo '%s' ya existe en la base de datos.") % field_name)
            else:
                raise UserError(_("Error técnico al crear el campo. Consulte los logs."))

    def _register_field_in_ir(self, field_name, selection_values=False):
        """Crea el registro en ir.model.fields para subtask.activity"""
        model_id = self.env['ir.model'].search([('model', '=', 'subtask.activity')], limit=1)
        if not model_id:
            raise UserError(_("Modelo subtask.activity no encontrado"))

        field_vals = {
            'name': field_name,
            'model_id': model_id.id,
            'field_description': self.field_label or self.field_name,
            'ttype': self.field_type,
            'state': 'manual',
            'store': True,
        }

        # Manejar campos de selección
        if self.field_type == 'selection' and selection_values:
            field_vals['selection'] = selection_values

        try:
            self.env['ir.model.fields'].create(field_vals)
            _logger.info("✅ Campo %s registrado en ir.model.fields", field_name)

        except Exception as e:
            _logger.error("❌ Error registrando campo: %s", str(e))
            raise UserError(_("Error al registrar el campo. Consulte los logs."))

    def _update_views(self, field_name):
        """Actualiza las vistas de subtask.activity para incluir el nuevo campo"""
        try:
            field_label = self.field_label or self.field_name

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
            
            # Vista Form de subtask.activity
            form_view = self.env.ref('task_planner.view_subtask_activity_form', raise_if_not_found=False)
            if form_view:
                arch_form = f"""
                <data>
                    <xpath expr="//field[@name='person']" position="after">
                        <field name="{field_name}" string="{field_label}"/>
                    </xpath>
                </data>
                """
                
                self.env['ir.ui.view'].create({
                    'name': f'subtask.activity.form.dynamic.{field_name}',
                    'model': 'subtask.activity',
                    'inherit_id': form_view.id,
                    'arch': arch_form,
                    'type': 'form',
                    'priority': 100,
                })

            # Vista Tree de subtask.activity
            tree_view = self.env.ref('task_planner.view_subtask_activity_tree', raise_if_not_found=False)
            if tree_view:
                arch_tree = f"""
                <data>
                    <xpath expr="//field[@name='person']" position="after">
                        <field name="{field_name}" string="{field_label}"/>
                    </xpath>
                </data>
                """
                
                self.env['ir.ui.view'].create({
                    'name': f'subtask.activity.tree.dynamic.{field_name}',
                    'model': 'subtask.activity',
                    'inherit_id': tree_view.id,
                    'arch': arch_tree,
                    'type': 'tree',
                    'priority': 100,
                })

            _logger.info("✅ Vistas actualizadas con campo %s", field_name)

        except Exception as e:
            _logger.error("❌ Error actualizando vistas: %s", str(e))
            raise UserError(_("Error al actualizar vistas. Consulte los logs."))

    def _safe_cache_clear(self):
        """Limpieza segura de cachés"""
        try:
            # Limpiar cachés básicos
            self.env.invalidate_all()
            if hasattr(self.env.registry, 'clear_cache'):
                self.env.registry.clear_cache()
            
            # Limpiar cachés de vistas
            self.env['ir.ui.view'].clear_caches()
            
            _logger.info("✅ Cachés limpiados correctamente")
            
        except Exception as e:
            _logger.warning("⚠️ Error limpiando cachés: %s", str(e))