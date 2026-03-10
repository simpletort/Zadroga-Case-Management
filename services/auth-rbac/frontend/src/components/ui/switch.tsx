import React from 'react';

export interface SwitchProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, 'type'> {
  /**
   * Label for the switch
   */
  label?: string;
  
  /**
   * Description text
   */
  description?: string;
  
  /**
   * Size of the switch
   * @default 'md'
   */
  size?: 'sm' | 'md' | 'lg';
}

/**
 * Switch Component
 * 
 * Accessible toggle switch for binary on/off states.
 * Meets WCAG 2.1 AA standards with proper ARIA attributes and keyboard navigation.
 * 
 * @example
 * ```tsx
 * <Switch label="Enable notifications" />
 * <Switch label="Dark mode" description="Toggle dark theme" />
 * <Switch size="lg" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
 * ```
 */
export const Switch = React.forwardRef<HTMLInputElement, SwitchProps>(
  (
    {
      label,
      description,
      size = 'md',
      className = '',
      id,
      disabled,
      checked,
      ...props
    },
    ref
  ) => {
    const generatedId = React.useId();
    const switchId = id || generatedId;
    
    const sizeStyles = {
      sm: {
        track: 'w-9 h-5',
        thumb: 'w-3.5 h-3.5',
        translate: 'translate-x-4',
      },
      md: {
        track: 'w-11 h-6',
        thumb: 'w-4 h-4',
        translate: 'translate-x-5',
      },
      lg: {
        track: 'w-14 h-7',
        thumb: 'w-5 h-5',
        translate: 'translate-x-7',
      },
    };
    
    const styles = sizeStyles[size];
    
    return (
      <div className={`flex items-start gap-3 ${className}`}>
        <div className="relative flex items-center">
          <input
            ref={ref}
            type="checkbox"
            id={switchId}
            role="switch"
            checked={checked}
            disabled={disabled}
            className="peer sr-only"
            aria-checked={checked}
            {...props}
          />
          <div
            className={`${styles.track} bg-slate-300 rounded-full transition-colors peer-checked:bg-blue-600 peer-focus:ring-2 peer-focus:ring-blue-500 peer-focus:ring-offset-2 peer-disabled:opacity-50 peer-disabled:cursor-not-allowed cursor-pointer`}
          >
            <div
              className={`${styles.thumb} bg-white rounded-full shadow-md transition-transform translate-x-1 peer-checked:${styles.translate} translate-y-1`}
            />
          </div>
        </div>
        
        {(label || description) && (
          <div className="flex-1">
            {label && (
              <label
                htmlFor={switchId}
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

Switch.displayName = 'Switch';
