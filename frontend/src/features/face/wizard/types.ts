/**
 * Shared types for the enrollment wizard.
 */

export type WizardStep =
  | 'consent'
  | 'details'
  | 'capture_front'
  | 'capture_left'
  | 'capture_right'
  | 'capture_expression_smile'
  | 'capture_expression_neutral'
  | 'review';

/** One persisted capture in the wizard state. */
export interface WizardCapture {
  /** Slug identifying the angle/expression — passed back to the backend. */
  angle:
    | 'front'
    | 'left'
    | 'right'
    | 'smile'
    | 'neutral';
  /** Raw 128-D descriptor as a plain number[] (ready to ship). */
  descriptor: number[];
  /** 0..1 quality at the moment of capture. */
  quality: number;
}

export interface WizardDetails {
  displayName: string;
  isChild: boolean;
}

/** Required minimum quality to count a capture as "passed". */
export const QUALITY_THRESHOLD = 0.8;

/** Captures needed before the wizard can advance to review. */
export const REQUIRED_CAPTURES = 5;

/** Minimum number of captures that must clear QUALITY_THRESHOLD. */
export const MIN_PASSING_CAPTURES = 4;

/** Consecutive good frames before auto-capture fires. */
export const AUTO_CAPTURE_STREAK = 3;

/** Consent text version saved on the backend. Bumped when the copy changes. */
export const CONSENT_TEXT_VERSION = 'v1.0';
