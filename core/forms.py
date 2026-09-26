from django import forms


class StyledFormMixin:
    """Apply the design-system classes to every widget so templates can
    render fields generically via components/field.html."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, (forms.CheckboxInput,)):
                css = "checkbox"
            elif isinstance(widget, (forms.CheckboxSelectMultiple, forms.RadioSelect)):
                css = ""
            elif isinstance(widget, forms.ClearableFileInput):
                css = "file-input"
            elif isinstance(widget, forms.Select):
                css = "input select"
            else:
                css = "input"
            if css:
                widget.attrs["class"] = f"{css} {widget.attrs.get('class', '')}".strip()
            if field.required and not isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("required", True)
            if self.errors.get(name):
                widget.attrs["aria-invalid"] = "true"
                widget.attrs["aria-describedby"] = f"{self.prefix + '-' if self.prefix else ''}{name}-error"
