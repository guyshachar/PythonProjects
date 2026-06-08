import { defineConfig } from 'vite'
import { VitePWA } from 'vite-plugin-pwa'
import { resolve } from 'path'

export default defineConfig({
  root: '.',
  base: './',
  server: {
    port: 3000,
    host: 'localhost',
    https: false, // Disable HTTPS for now to avoid SSL issues
    open: true,
    cors: true,
    strictPort: false, // Allow Vite to find another port if 3000 is busy
    hmr: {
      port: 3001,
      host: 'localhost'
    }
  },
  // Add redirect configuration for root path
  preview: {
    port: 3000,
    host: 'localhost',
    open: true
  },
  // Configure redirects
  define: {
    __VITE_APP_TITLE__: JSON.stringify('RefereeX PWA')
  },
  // Add middleware for root path redirect
  configureServer(server) {
    server.middlewares.use('/', (req, res, next) => {
      if (req.url === '/' || req.url === '/index.htmllll') {
        res.writeHead(302, { 'Location': '/refportal-pwa.html' });
        res.end();
      } else {
        next();
      }
    });
  },
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
    sourcemap: true,
    rollupOptions: {
      input: {
        main: resolve(__dirname, 'refportal-pwa.html')
      }
    }
  },
  plugins: [
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: [
        'favicon.ico',
        'apple-touch-icon.png',
        'masked-icon.svg',
        'images/**/*.png',
        'images/**/*.jpg',
        'images/**/*.jpeg',
        'images/**/*.gif',
        'images/**/*.svg',
        'css/**/*.css',
        'fonts/**/*.woff',
        'fonts/**/*.woff2',
        'fonts/**/*.ttf'
      ],
      manifest: {
        name: 'RefereeX - ניהול שופטים ומשחקים',
        short_name: 'RefereeX',
        description: 'מערכת ניהול שופטים ומשחקים מתקדמת',
        theme_color: '#2563eb',
        background_color: '#ffffff',
        display: 'standalone',
        orientation: 'portrait',
        scope: './',
        start_url: './refportal-pwa.html',
        lang: 'he',
        dir: 'rtl',
        icons: [
          {
            src: 'images/RefereeX_transparent_small.png',
            sizes: '640x640',
            type: 'image/png',
            purpose: 'any maskable'
          },
          {
            src: 'images/favicon.png',
            sizes: '192x192',
            type: 'image/png'
          },
          {
            src: 'images/favicon.png',
            sizes: '512x512',
            type: 'image/png'
          }
        ],
        categories: ['sports', 'productivity', 'utilities'],
        shortcuts: [
          {
            name: 'משחקים',
            short_name: 'משחקים',
            description: 'צפייה במשחקים',
            url: './refportal-pwa.html#games',
            icons: [{ src: 'images/RefereeX_transparent_small.png', sizes: '96x96' }]
          },
          {
            name: 'ביקורות',
            short_name: 'ביקורות',
            description: 'ביקורות שופטים',
            url: './refportal-pwa.html#reviews',
            icons: [{ src: 'images/RefereeX_transparent_small.png', sizes: '96x96' }]
          },
          {
            name: 'צ\'אט',
            short_name: 'צ\'אט',
            description: 'צ\'אט שופטים',
            url: './refportal-pwa.html#chat',
            icons: [{ src: 'images/RefereeX_transparent_small.png', sizes: '96x96' }]
          }
        ]
      },
      workbox: {
        globPatterns: [
          '**/*.{js,css,html,ico,png,svg,jpg,jpeg,gif,woff,woff2,ttf}'
        ],
        runtimeCaching: [
          {
            urlPattern: /^https:\/\/cdn\.plot\.ly\/.*/i,
            handler: 'CacheFirst',
            options: {
              cacheName: 'plotly-cache',
              expiration: {
                maxEntries: 10,
                maxAgeSeconds: 60 * 60 * 24 * 365 // 1 year
              }
            }
          },
          {
            urlPattern: /^https:\/\/.*\.(?:png|jpg|jpeg|svg|gif|webp)$/,
            handler: 'CacheFirst',
            options: {
              cacheName: 'images-cache',
              expiration: {
                maxEntries: 60,
                maxAgeSeconds: 60 * 60 * 24 * 30 // 30 days
              }
            }
          },
          {
            urlPattern: /^https:\/\/.*\.(?:woff|woff2|ttf|eot)$/,
            handler: 'CacheFirst',
            options: {
              cacheName: 'fonts-cache',
              expiration: {
                maxEntries: 10,
                maxAgeSeconds: 60 * 60 * 24 * 365 // 1 year
              }
            }
          },
          {
            urlPattern: /^https:\/\/.*\/api\/.*/,
            handler: 'NetworkFirst',
            options: {
              cacheName: 'api-cache',
              expiration: {
                maxEntries: 50,
                maxAgeSeconds: 60 * 5 // 5 minutes
              },
              networkTimeoutSeconds: 10
            }
          }
        ],
        cleanupOutdatedCaches: true,
        skipWaiting: true,
        clientsClaim: true
      },
      devOptions: {
        enabled: true,
        type: 'module',
        navigateFallback: 'refportal-pwa.html'
      }
    })
  ]
})