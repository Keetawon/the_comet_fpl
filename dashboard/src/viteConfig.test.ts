import { describe, expect, it } from 'vitest'
import viteConfig, { isAtomicDashboardPublishPath } from '../vite.config'

describe('Vite atomic dashboard publish watcher', () => {
  it('ignores transient public-data generations but keeps the installed generation watched', () => {
    expect(
      isAtomicDashboardPublishPath(
        String.raw`D:\repo\dashboard\public\.data.0123456789abcdef.tmp\players.json`,
      ),
    ).toBe(true)
    expect(
      isAtomicDashboardPublishPath(
        '/repo/dashboard/public/.data.0123456789abcdef.previous/manifest.json',
      ),
    ).toBe(true)
    expect(
      isAtomicDashboardPublishPath('/repo/dashboard/public/.data.0123456789abcdef.tmp'),
    ).toBe(true)

    expect(
      isAtomicDashboardPublishPath('/repo/dashboard/public/data/players.json'),
    ).toBe(false)
    expect(
      isAtomicDashboardPublishPath('/repo/dashboard/.data.0123456789abcdef.tmp/players.json'),
    ).toBe(false)
  })

  it('wires the narrow predicate into the dev-server watcher', () => {
    expect(viteConfig.server?.watch?.ignored).toBe(isAtomicDashboardPublishPath)
  })
})
