import { router, type Href } from 'expo-router';

/** Back to a tab screen: pop the stack down to the tabs instead of pushing a second tab navigator. */
export function goTab(href: Href) {
  if (router.canDismiss()) router.dismissTo(href);
  else router.replace(href);
}
