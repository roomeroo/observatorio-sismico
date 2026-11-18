import { defineConfig } from 'cypress';
import { spawnSync } from 'node:child_process';
import { resolve } from 'node:path';

export default defineConfig({
  e2e: {
    baseUrl: 'http://localhost:4200',
    supportFile: false,
    specPattern: 'cypress/e2e/**/*.cy.{js,jsx,ts,tsx}',
    viewportWidth: 1280,
    viewportHeight: 720,
    video: false,
    setupNodeEvents(on) {
      on('task', {
        /** Runs `docker compose <args>` from the repository root (used by the real-tunnel test). */
        compose(args: string[]) {
          const r = spawnSync('docker', ['compose', '--profile', 'tunnel', ...args], { cwd: resolve(__dirname, '..'), encoding: 'utf8' });
          if (r.status !== 0) throw new Error(`docker compose ${args.join(' ')} failed: ${r.stderr}`);
          return r.stdout;
        },
      });
    },
  },
});
