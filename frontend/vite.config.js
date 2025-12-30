import { defineConfig } from 'vite';
import solidPlugin from 'vite-plugin-solid';

export default defineConfig({
  plugins: [
    solidPlugin(),
  ],
  server: {
    host: "0.0.0.0",
    port: 3000,
    cors: true,
    proxy: {
      '/api': {
        target: 'http://localhost:5000/', // Your backend server's address and port
        changeOrigin: true,
        secure: false,
      },
    },
  }
});
