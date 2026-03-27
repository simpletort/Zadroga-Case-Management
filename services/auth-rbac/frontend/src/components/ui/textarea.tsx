import React from 'react';

export interface TextareaProps extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  /**
   * Label for the textarea
   */
  label?: string;
  
  /**
   * Error message to display
   */
  error?: string;
  
  /**
   * Helper text to display below textarea
   */
  helperText?: string;
  
  /**
   * Show character count
   * @default false
   */
  showCount?: boolean;
  
  /**
   * Full width textarea
   * @default false
   */
  fullWidth?: boolean;
}

/**
 * Textarea Component
 * 
 * Accessible multi-line text input with label, error states, and character count.
 * Meets WCAG 2.1 AA standards with proper labeling and error messaging.
 * 
 * @example
 * ```tsx
 * <Textarea label="Description" rows={4} />
 * <Textarea label="Notes" error="This field is required" />
 * <Textarea maxLength={500} showCount />
 * ```
 */
export const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
  (
    {
      label,
      error,
      helperText,
      showCount = false,
      fullWidth = false,
      className = '',
      id,
      required,
      disabled,
      maxLength,
      value,
      ...props
    },
    ref
  ) => {
    const generatedId = React.useId();
    const textareaId = id || generatedId;
    const errorId = `${textareaId}-error`;
    const helperTextId = `${textareaId}-helper`;
    
    const currentLength = typeof value === 'string' ? value.length : 0;
    
    const baseStyles = 'border border-slate-300 rounded-lg px-4 py-2 text-base transition-all focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:bg-slate-100 disabled:cursor-not-allowed resize-y';
    
    const errorStyles = error ? 'border-red-500 focus:ring-red-500' : '';
    
    const widthStyle = fullWidth ? 'w-full' : '';
    
    const textareaClasses = `${baseStyles} ${errorStyles} ${widthStyle} ${className}`;
    
    return (
      <div className={fullWidth ? 'w-full' : ''}>
        {label && (
          <label
            htmlFor={textareaId}
            className="block text-sm font-medium text-slate-700 mb-1.5"
          >
            {label}
            {required && <span className="text-red-500 ml-1" aria-label="required">*</span>}
          </label>
        )}
        
        <textarea
          ref={ref}
          id={textareaId}
          className={textareaClasses}
          disabled={disabled}
          required={required}
          maxLength={maxLength}
          value={value}
          aria-invalid={error ? 'true' : 'false'}
          aria-describedby={error ? errorId : helperText ? helperTextId : undefined}
          {...props}
        />
        
        <div className="flex items-start justify-between mt-1.5">
          <div className="flex-1">
            {error && (
              <p id={errorId} className="text-sm text-red-600" role="alert">
                {error}
              </p>
            )}
            
            {!error && helperText && (
              <p id={helperTextId} className="text-sm text-slate-600">
                {helperText}
              </p>
            )}
          </div>
          
          {showCount && maxLength && (
            <p className="text-sm text-slate-600 ml-2 flex-shrink-0">
              {currentLength}/{maxLength}
            </p>
          )}
        </div>
      </div>
    );
  }
);

Textarea.displayName = 'Textarea';
