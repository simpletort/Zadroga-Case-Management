import React from 'react';
import { AlertCircle, CheckCircle, Info, AlertTriangle, X } from 'lucide-react';

export interface AlertProps extends React.HTMLAttributes<HTMLDivElement> {
  /**
   * Alert variant
   * @default 'info'
   */
  variant?: 'success' | 'warning' | 'error' | 'info';
  
  /**
   * Alert title
   */
  title?: string;
  
  /**
   * Show dismiss button
   * @default false
   */
  dismissible?: boolean;
  
  /**
   * Dismiss callback
   */
  onDismiss?: () => void;
}

/**
 * Alert Component
 * 
 * Accessible alert/notification component for displaying important messages.
 * Meets WCAG 2.1 AA standards with proper ARIA roles and color contrast.
 * 
 * @example
 * ```tsx
 * <Alert variant="success" title="Success!">
 *   Your changes have been saved.
 * </Alert>
 * <Alert variant="error" dismissible onDismiss={() => {}}>
 *   An error occurred. Please try again.
 * </Alert>
 * ```
 */
export const Alert: React.FC<AlertProps> = ({
  variant = 'info',
  title,
  dismissible = false,
  onDismiss,
  className = '',
  children,
  ...props
}) => {
  const [isVisible, setIsVisible] = React.useState(true);
  
  const handleDismiss = () => {
    setIsVisible(false);
    onDismiss?.();
  };
  
  if (!isVisible) return null;
  
  const variants = {
    success: {
      container: 'bg-green-50 border-green-200 text-green-800',
      icon: CheckCircle,
      iconColor: 'text-green-600',
    },
    warning: {
      container: 'bg-yellow-50 border-yellow-200 text-yellow-900',
      icon: AlertTriangle,
      iconColor: 'text-yellow-600',
    },
    error: {
      container: 'bg-red-50 border-red-200 text-red-800',
      icon: AlertCircle,
      iconColor: 'text-red-600',
    },
    info: {
      container: 'bg-blue-50 border-blue-200 text-blue-800',
      icon: Info,
      iconColor: 'text-blue-600',
    },
  };
  
  const config = variants[variant];
  const Icon = config.icon;
  
  const roleMap = {
    success: 'status',
    warning: 'alert',
    error: 'alert',
    info: 'status',
  };
  
  return (
    <div
      role={roleMap[variant]}
      aria-live="polite"
      className={`flex gap-3 p-4 border rounded-lg ${config.container} ${className}`}
      {...props}
    >
      <Icon className={`w-5 h-5 flex-shrink-0 ${config.iconColor}`} aria-hidden="true" />
      
      <div className="flex-1 min-w-0">
        {title && (
          <h3 className="font-semibold text-sm mb-1">
            {title}
          </h3>
        )}
        {children && (
          <div className="text-sm">
            {children}
          </div>
        )}
      </div>
      
      {dismissible && (
        <button
          onClick={handleDismiss}
          className="flex-shrink-0 p-1 rounded hover:bg-black/5 transition-colors focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-current"
          aria-label="Dismiss alert"
        >
          <X className="w-4 h-4" />
        </button>
      )}
    </div>
  );
};
