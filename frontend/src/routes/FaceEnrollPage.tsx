/**
 * Wrapper route for the enrollment wizard.
 *
 * Kept thin so the wizard implementation can move without touching the
 * router. The wizard mounts its own FaceProvider; this page just makes
 * sure the user is authenticated (App.tsx already gates routes behind
 * auth, so this component is rendered only when auth.kind === 'user').
 */

import { EnrollmentWizard } from '../features/face/wizard';


export default function FaceEnrollPage() {
  return <EnrollmentWizard />;
}
