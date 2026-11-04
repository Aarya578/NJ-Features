frappe.listview_settings['Resource Reallocation Line'] = {
	add_fields: ['changed', 'move_type', 'present'],
	get_indicator(doc) {
		if (!doc.present) return [__('Absent'), 'gray', 'present,=,0'];
		if (doc.move_type === 'Manual override') return [__('Override'), 'purple', 'is_override,=,1'];
		if (doc.move_type === 'Untrained move') return [__('Untrained'), 'orange', 'move_type,=,Untrained move'];
		if (doc.changed) return [__('Moving'), 'blue', 'changed,=,1'];
		return [__('Stay'), 'green', 'changed,=,0'];
	},
};
