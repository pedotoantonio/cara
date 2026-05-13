/**
 * Public surface of the face recognition feature.
 *
 * Consumers should import only from here; the worker, context internals,
 * and component implementations are not part of the contract.
 */

export { FaceProvider, useFaceContext } from './FaceContext';
export { FaceOverlay } from './components/FaceOverlay';
export { useFaceDetection } from './hooks/useFaceDetection';
export type {
  FaceBox,
  FaceDetection,
  FaceProfile,
  FaceSettings,
} from './types';
