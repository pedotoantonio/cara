import { motion } from 'framer-motion';
import { CaraFace } from '@/components/avatar/CaraFace';
import { cn } from '@/lib/cn';

interface MessageBubbleProps {
  role: 'user' | 'assistant';
  content: string;
  streaming?: boolean;
  speaking?: boolean;
}

export function MessageBubble({ role, content, streaming, speaking }: MessageBubbleProps) {
  const isUser = role === 'user';
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.22, ease: [0.2, 0, 0, 1] }}
      className={cn(
        'flex items-start gap-2 my-3',
        isUser ? 'flex-row-reverse' : 'flex-row',
      )}
    >
      {!isUser && (
        <div className="flex-shrink-0 mt-1">
          <CaraFace
            size={36}
            energy={speaking ? 'speaking' : streaming ? 'thinking' : 'idle'}
            emotion="neutral"
          />
        </div>
      )}
      <div
        className={cn(
          'max-w-[78%] rounded-2xl px-4 py-2.5 shadow-1',
          isUser
            ? 'bg-accent-coral text-text-inverse rounded-tr-sm'
            : 'bg-bg-surface text-text-primary rounded-tl-sm border border-border-soft',
        )}
      >
        {content ? (
          <p className="whitespace-pre-wrap leading-relaxed text-base">
            {content}
            {streaming && (
              <span className="inline-block w-1.5 h-4 ml-1 align-middle bg-current opacity-60 animate-pulse" />
            )}
          </p>
        ) : (
          <ThinkingDots />
        )}
      </div>
    </motion.div>
  );
}

function ThinkingDots() {
  return (
    <span className="inline-flex items-center gap-1 py-1">
      {[0, 1, 2].map((i) => (
        <motion.span
          key={i}
          animate={{ opacity: [0.3, 1, 0.3], y: [0, -3, 0] }}
          transition={{ duration: 1, repeat: Infinity, delay: i * 0.18 }}
          className="inline-block w-1.5 h-1.5 rounded-full bg-text-muted"
        />
      ))}
    </span>
  );
}
