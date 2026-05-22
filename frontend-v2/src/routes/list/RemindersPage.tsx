import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AnimatePresence, motion } from 'framer-motion';
import { Skeleton, Card, CardSubtitle, Badge, Button, useToast } from '@/design/components';
import { Check, Clock } from '@phosphor-icons/react';
import {
  listUpcomingReminders,
  markReminderDone,
  snoozeReminder,
  type Reminder,
} from '@/api/reminders';

const CATEGORY_ACCENT: Record<string, 'sky' | 'coral' | 'mint' | 'lilac' | 'rose'> = {
  family: 'rose',
  health: 'mint',
  documents: 'lilac',
  events: 'sky',
};

export function RemindersPage() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const remQ = useQuery({
    queryKey: ['reminders.upcoming.list'],
    queryFn: () => listUpcomingReminders(60, 100),
    staleTime: 60_000,
  });

  const doneM = useMutation({
    mutationFn: (id: number) => markReminderDone(id),
    onMutate: async (id) => {
      await queryClient.cancelQueries({ queryKey: ['reminders.upcoming.list'] });
      const prev = queryClient.getQueryData<Reminder[]>(['reminders.upcoming.list']);
      queryClient.setQueryData<Reminder[]>(['reminders.upcoming.list'], (p) =>
        p ? p.filter((r) => r.id !== id) : p,
      );
      return { prev };
    },
    onError: (err, _id, ctx) => {
      if (ctx?.prev) queryClient.setQueryData(['reminders.upcoming.list'], ctx.prev);
      toast.push({ tone: 'coral', title: 'Errore', body: (err as Error).message });
    },
  });

  const snoozeM = useMutation({
    mutationFn: (id: number) => snoozeReminder(id, 1),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['reminders.upcoming.list'] });
      toast.push({ tone: 'sky', title: 'Posticipato di 1 ora' });
    },
  });

  const items = remQ.data ?? [];

  return (
    <div className="container-app py-4 space-y-3">
      <p className="text-sm text-text-muted px-1">
        Promemoria configurati dalla pagina <strong>Tu → Vita Quotidiana</strong>. Qui li vedi
        e li gestisci quando arrivano.
      </p>

      {remQ.isLoading && (
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-20 w-full" />
          ))}
        </div>
      )}

      {!remQ.isLoading && items.length === 0 && (
        <p className="text-text-muted text-center py-8 text-sm">
          Nessun promemoria nei prossimi mesi.
        </p>
      )}

      <ul className="space-y-2">
        <AnimatePresence>
          {items.map((r) => (
            <motion.li
              key={r.id}
              layout
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, x: 60 }}
            >
              <Card padding="base" elevation={1}>
                <div className="flex items-start justify-between gap-2">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <Badge tone={CATEGORY_ACCENT[r.category] ?? 'neutral'} size="sm">
                        {r.category}
                      </Badge>
                    </div>
                    <p className="font-medium">{r.title}</p>
                    <CardSubtitle>
                      {new Date(r.due_at).toLocaleString('it-IT', {
                        weekday: 'short',
                        day: '2-digit',
                        month: 'short',
                        hour: '2-digit',
                        minute: '2-digit',
                      })}
                    </CardSubtitle>
                  </div>
                  <div className="flex flex-col gap-1">
                    <Button
                      size="sm"
                      variant="primary"
                      leftIcon={<Check size={14} />}
                      onClick={() => doneM.mutate(r.id)}
                    >
                      Fatto
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      leftIcon={<Clock size={14} />}
                      onClick={() => snoozeM.mutate(r.id)}
                    >
                      +1h
                    </Button>
                  </div>
                </div>
              </Card>
            </motion.li>
          ))}
        </AnimatePresence>
      </ul>
    </div>
  );
}
