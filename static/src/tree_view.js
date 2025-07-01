odoo.define('task_planner.tree_view', function (require) {
    "use strict";

    var ListRenderer = require('web.ListRenderer');

    ListRenderer.include({
        _renderRow: function (record) {
            var $row = this._super.apply(this, arguments);
            
            if (record.data.subtask_ids && record.data.subtask_ids.count > 0) {
                var $button = $row.find('.o_expand_button');
                $button.addClass('fa fa-chevron-right');
                
                $button.on('click', function (e) {
                    e.preventDefault();
                    e.stopPropagation();
                    
                    // Toggle icon
                    $button.toggleClass('fa-chevron-right fa-chevron-down');
                    
                    // Find the subtasks container
                    var $subtasks = $row.next('tr.o_subtree');
                    if ($subtasks.length) {
                        $subtasks.toggle();
                    }
                });
            }
            
            return $row;
        },

        _render: function () {
            return this._super.apply(this, arguments);
        }
    });
});
