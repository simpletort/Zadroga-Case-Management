import React from 'react';

export interface RadioProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, 'type'> {
  /**
   * Label for the radio button
   */
  label?: string;
  
  /**
   * Description text for the radio option
   */
  description?: string;
}

export interface RadioGroupProps {
  /**
   * Radio group label
   */
  label?: string;
  
  /**
   * Error message to display
   */
  error?: string;
  
  /**
   * Helper text to display
   */
  helperText?: string;
  
  /**
   * Radio options
   */
  options: Array<{
    value: string;
    label: string;
    description?: string;
    disabled?: boolean;
  }>;
  
  /**
   * Name for the radio group
   */
  name: string;
  
  /**
   * Currently selected value
   */
  value?: string;
  
  /**
   * Change handler
   */
  onChange?: (value: string) => void;
}

/**
 * Radio Component
 * 
 * Individual radio button component.
 * 
 * @example
 * ```tsx
 * <Radio name="plan" value="basic" label="Basic Plan" />
 * ```
 */
export const Radio = React.forwardRef<HTMLInputElement, RadioProps>(
  (
    {
      label,
      description,
      className = '',
      id,
      disabled,
      ...props
    },
    ref
  ) => {
    const generatedId = React.useId();
    const radioId = id || generatedId;
    
    return (
      <div className={`flex items-start gap-3 ${className}`}>
        <div className="relative flex items-center h-5">
          <input
            ref={ref}
            type="radio"
            id={radioId}
            disabled={disabled}
            className="peer sr-only"
            {...props}
          />
          <div className="w-5 h-5 border-2 border-slate-300 rounded-full transition-all peer-checked:border-blue-600 peer-focus:ring-2 peer-focus:ring-blue-500 peer-focus:ring-offset-2 peer-disabled:bg-slate-100 peer-disabled:cursor-not-allowed flex items-center justify-center">
            <div className="w-2.5 h-2.5 rounded-full bg-blue-600 scale-0 peer-checked:scale-100 transition-transform" />
          </div>
        </div>
        
        {(label || description) && (
          <div className="flex-1">
            {label && (
              <label
                htmlFor={radioId}
                className="block text-sm font-medium text-slate-700 cursor-pointer select-none"
              >
                {label}
              </label>
            )}
            {description && (
              <p className="text-sm text-slate-600 mt-0.5">
                {description}
              </p>
            )}
          </div>
        )}
      </div>
    );
  }
);

Radio.displayName = 'Radio';

/**
 * RadioGroup Component
 * 
 * Accessible radio button group with label and error states.
 * Meets WCAG 2.1 AA standards with proper ARIA attributes.
 * 
 * @example
 * ```tsx
 * <RadioGroup
 *   label="Select a plan"
 *   name="plan"
 *   value={selectedPlan}
 *   onChange={setSelectedPlan}
 *   options={[
 *     { value: 'basic', label: 'Basic', description: '$10/month' },
 *     { value: 'pro', label: 'Pro', description: '$20/month' }
 *   ]}
 * />
 * ```
 */
export const RadioGroup: React.FC<RadioGroupProps> = ({
  label,
  error,
  helperText,
  options,
  name,
  value,
  onChange,
}) => {
  const generatedId = React.useId();
  const groupId = `radio-group-${generatedId}`;
  const errorId = `${groupId}-error`;
  const helperTextId = `${groupId}-helper`;
  
  return (
    <div role="radiogroup" aria-labelledby={label ? groupId : undefined}>
      {label && (
        <p id={groupId} className="text-sm font-medium text-slate-700 mb-3">
          {label}
        </p>
      )}
      
      <div className="space-y-3">
        {options.map((option) => (
          <Radio
            key={option.value}
            name={name}
            value={option.value}
            label={option.label}
            description={option.description}
            checked={value === option.value}
            disabled={option.disabled}
            onChange={() => onChange?.(option.value)}
          />
        ))}
      </div>
      
      {error && (
        <p id={errorId} className="mt-2 text-sm text-red-600" role="alert">
          {error}
        </p>
      )}
      
      {!error && helperText && (
        <p id={helperTextId} className="mt-2 text-sm text-slate-600">
          {helperText}
        </p>
      )}
    </div>
  );
};
