import React from 'react';
import { Check } from 'lucide-react';

export interface CheckboxProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, 'type'> {
  /**
   * Label for the checkbox
   */
  label?: string;
  
  /**
   * Error message to display
   */
  error?: string;
  
  /**
   * Helper text to display below checkbox
   */
  helperText?: string;
  
  /**
   * Indeterminate state
   * @default false
   */
  indeterminate?: boolean;
}

/**
 * Checkbox Component
 * 
 * Accessible checkbox with custom styling and indeterminate state support.
 * Meets WCAG 2.1 AA standards with proper focus and keyboard navigation.
 * 
 * @example
 * ```tsx
 * <Checkbox label="Accept terms and conditions" />
 * <Checkbox label="Select all" indeterminate />
 * <Checkbox error="You must accept to continue" />
 * ```
 */
export const Checkbox = React.forwardRef<HTMLInputElement, CheckboxProps>(
  (
    {
      label,
      error,
      helperText,
      indeterminate = false,
      className = '',
      id,
      disabled,
      checked,
      ...props
    },
    ref
  ) => {
    const generatedId = React.useId();
    const checkboxId = id || generatedId;
    const errorId = `${checkboxId}-error`;
    const helperTextId = `${checkboxId}-helper`;
    
    const internalRef = React.useRef<HTMLInputElement>(null);
    const combinedRef = ref || internalRef;
    
    React.useEffect(() => {
      const checkbox = typeof combinedRef === 'function' ? null : combinedRef.current;
      if (checkbox) {
        checkbox.indeterminate = indeterminate;
      }
    }, [indeterminate, combinedRef]);
    
    return (
      <div className={className}>
        <div className="flex items-start gap-2">
          <div className="relative flex items-center h-5">
            <input
              ref={combinedRef}
              type="checkbox"
              id={checkboxId}
              checked={checked}
              disabled={disabled}
              className="peer sr-only"
              aria-invalid={error ? 'true' : 'false'}
              aria-describedby={error ? errorId : helperText ? helperTextId : undefined}
              {...props}
            />
            <div className="w-5 h-5 border-2 border-slate-300 rounded transition-all peer-checked:bg-blue-600 peer-checked:border-blue-600 peer-indeterminate:bg-blue-600 peer-indeterminate:border-blue-600 peer-focus:ring-2 peer-focus:ring-blue-500 peer-focus:ring-offset-2 peer-disabled:bg-slate-100 peer-disabled:cursor-not-allowed flex items-center justify-center">
              {(checked || indeterminate) && (
                <Check className="w-3.5 h-3.5 text-white" strokeWidth={3} />
              )}
            </div>
          </div>
          
          {label && (
            <label
              htmlFor={checkboxId}
              className="text-sm font-medium text-slate-700 cursor-pointer select-none"
            >
              {label}
            </label>
          )}
        </div>
        
        {error && (
          <p id={errorId} className="mt-1.5 ml-7 text-sm text-red-600" role="alert">
            {error}
          </p>
        )}
        
        {!error && helperText && (
          <p id={helperTextId} className="mt-1.5 ml-7 text-sm text-slate-600">
            {helperText}
          </p>
        )}
      </div>
    );
  }
);

Checkbox.displayName = 'Checkbox';
