import { useId, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";

interface FieldProps {
  label: string;
  hint?: string;
  error?: string | null;
  children: (props: { id: string; "aria-describedby": string | undefined; "aria-invalid": boolean }) => ReactNode;
}

export function Field({ label, hint, error, children }: FieldProps) {
  const id = useId();
  const describedBy = [hint ? `${id}-hint` : null, error ? `${id}-error` : null].filter(Boolean).join(" ") || undefined;
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {children({ id, "aria-describedby": describedBy, "aria-invalid": Boolean(error) })}
      {hint ? (
        <p className="field__hint" id={`${id}-hint`}>
          {hint}
        </p>
      ) : null}
      {error ? (
        <p className="form-error" id={`${id}-error`} role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}

type TextProps = InputHTMLAttributes<HTMLInputElement> & { label: string; hint?: string; error?: string | null };

export function TextField({ label, hint, error, ...rest }: TextProps) {
  return <Field label={label} hint={hint} error={error}>{(aria) => <input {...aria} {...rest} />}</Field>;
}

type AreaProps = TextareaHTMLAttributes<HTMLTextAreaElement> & { label: string; hint?: string; error?: string | null };

export function TextAreaField({ label, hint, error, ...rest }: AreaProps) {
  return <Field label={label} hint={hint} error={error}>{(aria) => <textarea {...aria} {...rest} />}</Field>;
}

type SelectProps = SelectHTMLAttributes<HTMLSelectElement> & { label: string; hint?: string; options: { value: string; label: string }[] };

export function SelectField({ label, hint, options, ...rest }: SelectProps) {
  return (
    <Field label={label} hint={hint}>
      {(aria) => (
        <select {...aria} {...rest}>
          {options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      )}
    </Field>
  );
}

interface ToggleProps {
  label: string;
  hint?: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
}

export function Toggle({ label, hint, checked, onChange, disabled }: ToggleProps) {
  const id = useId();
  return (
    <div className="toggle">
      <div className="toggle__text">
        <label htmlFor={id}>{label}</label>
        {hint ? <p className="field__hint">{hint}</p> : null}
      </div>
      <input id={id} type="checkbox" role="switch" checked={checked} disabled={disabled} onChange={(event) => onChange(event.target.checked)} />
    </div>
  );
}
