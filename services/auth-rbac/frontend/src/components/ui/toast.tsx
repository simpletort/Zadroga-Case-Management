import React from 'react';
import { X, CheckCircle, AlertCircle, Info, AlertTriangle } from 'lucide-react';

export interface Toast {
  id: string;
  variant: 'success' | 'error' | 'warning' | 'info';
  title?: string;
  message: string;
  duration?: number;
}

export interface ToastProps extends Toast {
  onDismiss: (id: string) => void;
}

/**
 * Toast Component
 * 
 * Individual toast notification.
 */
const ToastItem: React.FC<ToastProps> = ({
  id,
  variant,
  title,
  message,
  duration = 5000,
  onDismiss,
}) => {
  React.useEffect(() => {
    if (duration > 0) {
      const timer = setTimeout(() => {
        onDismiss(id);
      }, duration);
      
      return () => clearTimeout(timer);
    }
  }, [id, duration, onDismiss]);
  
  const variants = {
    success: {
      icon: CheckCircle,
      iconColor: 'text-green-600',
      bgColor: 'bg-green-50',
      borderColor: 'border-green-200',
    },
    error: {
      icon: AlertCircle,
      iconColor: 'text-red-600',
      bgColor: 'bg-red-50',
      borderColor: 'border-red-200',
    },
    warning: {
      icon: AlertTriangle,
      iconColor: 'text-yellow-600',
      bgColor: 'bg-yellow-50',
      borderColor: 'border-yellow-200',
    },
    info: {
      icon: Info,
      iconColor: 'text-blue-600',
      bgColor: 'bg-blue-50',
      borderColor: 'border-blue-200',
    },
  };
  
  const config = variants[variant];
  const Icon = config.icon;
  
  return (
    <div
      role="alert"
      aria-live="polite"
      className={`flex items-start gap-3 p-4 ${config.bgColor} border ${config.borderColor} rounded-lg shadow-lg min-w-[320px] max-w-md animate-in slide-in-from-right`}
    >
      <Icon className={`w-5 h-5 flex-shrink-0 ${config.iconColor}`} />
      
      <div className="flex-1 min-w-0">
        {title && (
          <h4 className="font-semibold text-sm text-slate-900 mb-1">
            {title}
          </h4>
        )}
        <p className="text-sm text-slate-700">
          {message}
        </p>
      </div>
      
      <button
        onClick={() => onDismiss(id)}
        className="flex-shrink-0 p-1 text-slate-400 hover:text-slate-600 rounded transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500"
        aria-label="Dismiss notification"
      >
        <X className="w-4 h-4" />
      </button>
    </div>
  );
};

interface ToastContainerProps {
  toasts: Toast[];
  onDismiss: (id: string) => void;
}

/**
 * ToastContainer Component
 * 
 * Container for displaying multiple toast notifications.
 * 
 * @example
 * ```tsx
 * const [toasts, setToasts] = useState<Toast[]>([]);
 * 
 * const addToast = (toast: Omit<Toast, 'id'>) => {
 *   setToasts(prev => [...prev, { ...toast, id: Date.now().toString() }]);
 * };
 * 
 * <ToastContainer
 *   toasts={toasts}
 *   onDismiss={(id) => setToasts(prev => prev.filter(t => t.id !== id))}
 * />
 * ```
 */
const ToastContainerInner: React.FC<ToastContainerProps> = ({
  toasts,
  onDismiss,
}) => {
  return (
    <div
      className="fixed top-4 right-4 z-50 flex flex-col gap-2"
      aria-live="polite"
      aria-atomic="false"
    >
      {toasts.map((toast) => (
        <ToastItem key={toast.id} {...toast} onDismiss={onDismiss} />
      ))}
    </div>
  );
};

/**
 * Hook for managing toasts
 */
export const useToast = () => {
  const [toasts, setToasts] = React.useState<Toast[]>([]);
  
  const addToast = React.useCallback((toast: Omit<Toast, 'id'>) => {
    const id = Date.now().toString();
    setToasts((prev) => [...prev, { ...toast, id }]);
    return id;
  }, []);
  
  const dismissToast = React.useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);
  
  const dismissAll = React.useCallback(() => {
    setToasts([]);
  }, []);
  
  return {
    toasts,
    addToast,
    dismissToast,
    dismissAll,
  };
};

/**
 * ToastContainer wrapper that uses the toast hook internally
 * Use this when you need a standalone ToastContainer
 */
export const ToastContainer: React.FC = () => {
  const { toasts, dismissToast } = useToast();
  
  return <ToastContainerInner toasts={toasts} onDismiss={dismissToast} />;
};