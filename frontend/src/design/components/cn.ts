// Lightweight classnames helper. No external dep.
export function cn(...args: Array<string | false | null | undefined>): string {
  return args.filter(Boolean).join(' ');
}
