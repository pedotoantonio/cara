/**
 * Public surface of the face recognition feature.
 *
 * Consumers should import only from here; the worker, context internals,
 * and component implementations are not part of the contract.
 */

export { FaceProvider, useFaceContext } from './FaceContext';
export {
  ActiveProfileProvider,
  useActiveProfile,
  type ActiveProfile,
} from './ActiveProfileContext';
export { ActiveProfileBadge } from './components/ActiveProfileBadge';
export { FaceOverlay } from './components/FaceOverlay';
export { useFaceDetection } from './hooks/useFaceDetection';
export { canPerformAction, useChildSafe } from './permissions';
export type {
  FaceBox,
  FaceDetection,
  FaceEvent,
  FaceEventHandler,
  FaceIdentity,
  FaceProfile,
  FaceSettings,
  StoredDescriptor,
} from './types';
