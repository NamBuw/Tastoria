import { Redirect } from 'expo-router';

// Native startup; HTTP / is served directly as the public landing by nginx.
export default function Index() {
  return <Redirect href="/bep" />;
}
