import React from 'react';
import { ChevronDown } from 'lucide-react';

export interface SelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {
  /**
   * Label for the select
   */
  label?: string;
  
  /**
   * Error message to display
   */
  error?: string;
  
  /**
   * Helper text to display below select
   */
  helperText?: string;
  
  /**
   * Select options
   */
  options?: Array<{ value: string; label: string }>;
  
  /**
   * Placeholder text
   */
  placeholder?: string;
  
  /**
   * Full width select
   * @default false
   */
  fullWidth?: boolean;
}

/**
 * Select Component
 * 
 * Accessible dropdown select with label and error states.
 * Meets WCAG 2.1 AA standards with proper labeling.
 * 
 * @example
 * ```tsx
 * <Select
 *   label="Country"
 *   options={[
 *     { value: 'us', label: 'United States' },
 *     { value: 'ca', label: 'Canada' }
 *   ]}
 * />
 * ```
 */
export const Select = React.forwardRef<HTMLSelectElement, SelectProps>(
  (
    {
      label,
      error,
      helperText,
      options = [],
      placeholder,
      fullWidth = false,
      className = '',
      id,
      required,
      disabled,
      children,
      ...props
    },
    ref
  ) => {
    const generatedId = React.useId();
    const selectId = id || generatedId;
    const errorId = `${selectId}-error`;
    const helperTextId = `${selectId}-helper`;
    
    const baseStyles = 'border border-slate-300 rounded-lg px-4 py-2 pr-10 text-base transition-all focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:bg-slate-100 disabled:cursor-not-allowed appearance-none bg-white';
    
    const errorStyles = error ? 'border-red-500 focus:ring-red-500' : '';
    
    const widthStyle = fullWidth ? 'w-full' : '';
    
    const selectClasses = `${baseStyles} ${errorStyles} ${widthStyle} ${className}`;
    
    return (
      <div className={fullWidth ? 'w-full' : ''}>
        {label && (
          <label
            htmlFor={selectId}
            className="block text-sm font-medium text-slate-700 mb-1.5"
          >
            {label}
            {required && <span className="text-red-500 ml-1" aria-label="required">*</span>}
          </label>
        )}
        
        <div className="relative">
          <select
            ref={ref}
            id={selectId}
            className={selectClasses}
            disabled={disabled}
            required={required}
            aria-invalid={error ? 'true' : 'false'}
            aria-describedby={error ? errorId : helperText ? helperTextId : undefined}
            {...props}
          >
            {placeholder && (
              <option value="" disabled>
                {placeholder}
              </option>
            )}
            {options.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
            {children}
          </select>
          
          <div className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none">
            <ChevronDown className="w-5 h-5" />
          </div>
        </div>
        
        {error && (
          <p id={errorId} className="mt-1.5 text-sm text-red-600" role="alert">
            {error}
          </p>
        )}
        
        {!error && helperText && (
          <p id={helperTextId} className="mt-1.5 text-sm text-slate-600">
            {helperText}
          </p>
        )}
      </div>
    );
  }
);

Select.displayName = 'Select';
