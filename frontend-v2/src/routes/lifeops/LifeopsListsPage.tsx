// LifeopsListsPage — overview di TUTTE le liste (multi-lista).
//
// Differente dalla v1 /list/shopping che mostrava la singola lista spesa:
// qui vedi tutte le liste (todo, shopping, viaggio, regali, …) come card
// cliccabili. Tap → /lifeops/lists/:slug per il dettaglio.

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { Plus, Lock, Users } from '@phosphor-icons/react';
import { Button, Skeleton, useToast } from '@/design/components';
import {
  getLists,
  createList,
  type LifeopsList,
} from '@/api/lifeopsLists';

const SCOPE_LABEL: Record<string, { label: string; Icon: typeof Lock }> = {
  user: { label: 'Privata', Icon: Lock },
  family: { label: 'Famiglia', Icon: Users },
  shared: { label: 'Condivisa', Icon: Users },
};

export function LifeopsListsPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const toast = useToast();
  const [showCreate, setShowCreate] = useState(false);
  const [newTitle, setNewTitle] = useState('');
  const [newScope, setNewScope] = useState<'user' | 'family'>('user');

  const listsQ = useQuery({
    queryKey: ['lifeops', 'lists'],
    queryFn: () => getLists('all', false),
    staleTime: 30_000,
  });

  const createM = useMutation({
    mutationFn: (vars: { title: string; scope: 'user' | 'family' }) =>
      createList({
        slug: slugify(vars.title),
        title: vars.title,
        scope: vars.scope,
      }),
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: ['lifeops', 'lists'] });
      setShowCreate(false);
      setNewTitle('');
      toast.push({ tone: 'mint', title: 'Lista creata', body: created.title });
      navigate(`/lifeops/lists/${created.slug}`);
    },
    onError: (err: Error) => {
      toast.push({
        tone: 'coral',
        title: 'Errore',
        body: err.message || 'Non sono riuscita a creare la lista',
      });
    },
  });

  return (
    <div className="px-4 md:px-6 lg:px-8 py-4 max-w-3xl mx-auto">
      <header className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="font-display text-2xl text-text-primary">
            Le mie liste
          </h1>
          <p className="text-sm text-text-muted">
            Liste personali o di famiglia per qualsiasi cosa.
          </p>
        </div>
        <Button
          size="sm"
          leftIcon={<Plus size={16} />}
          onClick={() => setShowCreate(true)}
        >
          Nuova
        </Button>
      </header>

      {/* Form crea — collassabile */}
      {showCreate && (
        <div className="mb-4 p-3 rounded-xl border border-border-soft bg-bg-elevated">
          <input
            type="text"
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
            placeholder="Nome lista (es. Viaggio in Sicilia)"
            className="w-full px-3 py-2 mb-2 rounded-md border border-border-soft bg-bg-base text-text-primary"
            autoFocus
          />
          <div className="flex gap-2 mb-2">
            <button
              onClick={() => setNewScope('user')}
              className={`flex-1 px-3 py-1.5 rounded-md text-sm ${newScope === 'user' ? 'bg-accent-coral/15 border border-accent-coral/40 text-accent-coral' : 'bg-bg-base border border-border-soft text-text-muted'}`}
            >
              <Lock size={14} className="inline mr-1" /> Privata
            </button>
            <button
              onClick={() => setNewScope('family')}
              className={`flex-1 px-3 py-1.5 rounded-md text-sm ${newScope === 'family' ? 'bg-accent-mint/15 border border-accent-mint/40 text-accent-mint' : 'bg-bg-base border border-border-soft text-text-muted'}`}
            >
              <Users size={14} className="inline mr-1" /> Famiglia
            </button>
          </div>
          <div className="flex gap-2">
            <Button
              size="sm"
              fullWidth
              disabled={!newTitle.trim() || createM.isPending}
              onClick={() => createM.mutate({ title: newTitle.trim(), scope: newScope })}
            >
              Crea lista
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setShowCreate(false)}
            >
              Annulla
            </Button>
          </div>
        </div>
      )}

      {/* Grid liste */}
      {listsQ.isLoading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
        </div>
      ) : listsQ.isError ? (
        <p className="text-sm text-accent-coral">
          Non riesco a caricare le liste.
        </p>
      ) : listsQ.data && listsQ.data.length > 0 ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {listsQ.data.map((list) => (
            <ListCard key={list.id} list={list} />
          ))}
        </div>
      ) : (
        <div className="text-center py-12">
          <p className="text-text-muted mb-2">Non hai ancora nessuna lista.</p>
          <Button size="sm" onClick={() => setShowCreate(true)}>
            Crea la prima
          </Button>
        </div>
      )}
    </div>
  );
}

function ListCard({ list }: { list: LifeopsList }) {
  const navigate = useNavigate();
  const scope = SCOPE_LABEL[list.scope] ?? SCOPE_LABEL.user;
  const ScopeIcon = scope.Icon;
  return (
    <button
      onClick={() => navigate(`/lifeops/lists/${list.slug}`)}
      className="text-left p-4 rounded-xl border border-border-soft bg-bg-elevated hover:bg-bg-hover transition-colors shadow-1"
    >
      <h3 className="font-display text-lg text-text-primary mb-1">
        {list.title}
      </h3>
      <div className="flex items-center gap-2 text-xs text-text-muted">
        <span className="inline-flex items-center gap-1">
          <ScopeIcon size={12} />
          {scope.label}
        </span>
        <span>·</span>
        <span>slug: {list.slug}</span>
      </div>
    </button>
  );
}

function slugify(title: string): string {
  return title
    .toLowerCase()
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_|_$/g, '')
    .slice(0, 48);
}
