import React from 'react';
import { cn } from '../lib/utils';

interface DeadlineIndicatorProps {
  status: 'safe' | 'warning' | 'critical';
  type: string;
  date: string;
  daysRemaining: number;
  size?: 'sm' | 'md' | 'lg';
}

export function DeadlineIndicator({ status, type, date, daysRemaining, size = 'md' }: DeadlineIndicatorProps) {
  const statusConfig = {
    safe: {
      bg: 'bg-green-100',
      text: 'text-green-800',
      border: 'border-green-300',
      dot: 'bg-green-500'
    },
    warning: {
      bg: 'bg-yellow-100',
      text: 'text-yellow-800',
      border: 'border-yellow-300',
      dot: 'bg-yellow-500'
    },
    critical: {
      bg: 'bg-red-100',
      text: 'text-red-800',
      border: 'border-red-300',
      dot: 'bg-red-500'
    }
  };

  const config = statusConfig[status];
  
  const sizeClasses = {
    sm: 'px-2 py-1 text-xs',
    md: 'px-3 py-1.5 text-sm',
    lg: 'px-4 py-2 text-base'
  };

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  };

  const getDaysText = (days: number) => {
    if (days < 0) return 'Completed';
    if (days === 0) return 'Due today';
    if (days === 1) return '1 day left';
    return `${days} days left`;
  };

  return (
    <div className={cn(
      'inline-flex items-center gap-2 rounded-md border',
      config.bg,
      config.border,
      sizeClasses[size]
    )}>
      <div className={cn('w-2 h-2 rounded-full', config.dot)} />
      <div className="flex flex-col">
        <span className={cn('font-medium', config.text)}>{type}</span>
        <span className={cn('text-xs', config.text, 'opacity-80')}>
          {formatDate(date)} • {getDaysText(daysRemaining)}
        </span>
      </div>
    </div>
  );
}
