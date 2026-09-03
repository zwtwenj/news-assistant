import PodcastList from "@/components/PodcastList";

export default function PodcastHistoryPage() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-black dark:text-zinc-50">我的播客</h1>
        <p className="mt-1 text-sm text-zinc-500">
          点击「开始生成」即入库排队；生成中与失败的条目也会保留在列表
        </p>
      </div>
      <PodcastList />
    </div>
  );
}
