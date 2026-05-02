import { useOutletContext } from 'react-router-dom';

import type { User } from '../api/auth';
import { Chat } from '../components/Chat';

export function ChatPage() {
  const { user } = useOutletContext<{ user: User }>();
  return <Chat user={user} />;
}
