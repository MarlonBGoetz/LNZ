import { installInterceptor } from './interceptor';

// MAIN-world entry, injected at document_start before the site's own scripts.
installInterceptor({ win: window });
