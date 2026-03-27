import React from 'react';
import { User } from 'lucide-react';

export interface AvatarProps {
  /**
   * Avatar source image URL
   */
  src?: string;
  
  /**
   * Alt text for image
   */
  alt?: string;
  
  /**
   * Initials to display (if no image)
   */
  initials?: string;
  
  /**
   * Avatar size
   * @default 'md'
   */
  size?: 'xs' | 'sm' | 'md' | 'lg' | 'xl';
  
  /**
   * Avatar shape
   * @default 'circle'
   */
  shape?: 'circle' | 'square';
  
  /**
   * Status indicator
   */
  status?: 'online' | 'offline' | 'away' | 'busy';
}

/**
 * Avatar Component
 * 
 * Display user avatar with image, initials, or icon fallback.
 * Accessible with proper alt text.
 * 
 * @example
 * ```tsx
 * <Avatar src="/user.jpg" alt="John Doe" />
 * <Avatar initials="JD" status="online" />
 * <Avatar size="lg" />
 * ```
 */
export const Avatar: React.FC<AvatarProps> = ({
  src,
  alt = 'Avatar',
  initials,
  size = 'md',
  shape = 'circle',
  status,
}) => {
  const [imageError, setImageError] = React.useState(false);
  
  const sizeStyles = {
    xs: 'w-6 h-6 text-xs',
    sm: 'w-8 h-8 text-sm',
    md: 'w-10 h-10 text-base',
    lg: 'w-12 h-12 text-lg',
    xl: 'w-16 h-16 text-xl',
  };
  
  const shapeStyles = {
    circle: 'rounded-full',
    square: 'rounded-lg',
  };
  
  const statusColors = {
    online: 'bg-green-500',
    offline: 'bg-slate-400',
    away: 'bg-yellow-500',
    busy: 'bg-red-500',
  };
  
  const statusSizes = {
    xs: 'w-1.5 h-1.5',
    sm: 'w-2 h-2',
    md: 'w-2.5 h-2.5',
    lg: 'w-3 h-3',
    xl: 'w-4 h-4',
  };
  
  const showImage = src && !imageError;
  const showInitials = !showImage && initials;
  const showIcon = !showImage && !showInitials;
  
  return (
    <div className="relative inline-block">
      <div
        className={`${sizeStyles[size]} ${shapeStyles[shape]} bg-slate-200 flex items-center justify-center overflow-hidden font-semibold text-slate-700`}
      >
        {showImage && (
          <img
            src={src}
            alt={alt}
            className="w-full h-full object-cover"
            onError={() => setImageError(true)}
          />
        )}
        
        {showInitials && (
          <span>{initials.toUpperCase()}</span>
        )}
        
        {showIcon && (
          <User className="w-1/2 h-1/2" />
        )}
      </div>
      
      {status && (
        <span
          className={`absolute bottom-0 right-0 ${statusSizes[size]} ${statusColors[status]} border-2 border-white rounded-full`}
          aria-label={`Status: ${status}`}
        />
      )}
    </div>
  );
};
