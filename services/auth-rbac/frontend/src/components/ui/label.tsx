import React from 'react';

export interface LabelProps extends React.LabelHTMLAttributes<HTMLLabelElement> {
  /**
   * Required field indicator
   * @default false
   */
  required?: boolean;
  
  /**
   * Disabled state
   * @default false
   */
  disabled?: boolean;
}

/**
 * Label Component
 * 
 * Form label with optional required indicator.
 * Accessible with proper for/htmlFor association.
 * 
 * @example
 * ```tsx
 * <Label htmlFor="email" required>Email Address</Label>
 * <Label htmlFor="notes">Additional Notes</Label>
 * ```
 */
export const Label: React.FC<LabelProps> = ({
  required = false,
  disabled = false,
  className = '',
  children,
  ...props
}) => {
  return (
    <label
      className={`block text-sm font-medium ${
        disabled ? 'text-slate-400' : 'text-slate-700'
      } ${className}`}
      {...props}
    >
      {children}
      {required && (
        <span className="text-red-500 ml-1" aria-label="required">
          *
        </span>
      )}
    </label>
  );
};
