import StoryGamePage from "../../../../components/StoryGamePage";

export const metadata = { robots: { index: false, follow: false } };

export default async function GamePage({ params }) {
  const { projectId } = await params;
  return <StoryGamePage projectId={projectId} />;
}
