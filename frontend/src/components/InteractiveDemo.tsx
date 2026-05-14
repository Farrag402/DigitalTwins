import React, { useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle, CardFooter } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { Volume2, Loader2 } from "lucide-react";

export function InteractiveDemo() {
  const [isGeneratingAnswer, setIsGeneratingAnswer] = useState(false);
  const [question, setQuestion] = useState("");
  const [professor, setProfessor] = useState("");

  const handleAskProfessor = (e: React.FormEvent) => {
    e.preventDefault();
    if (!question || !professor) return;

    setIsGeneratingAnswer(true);
    // Mocking an API call delay
    setTimeout(() => {
      setIsGeneratingAnswer(false);
      alert(`تم تجهيز إجابة افتراضية من ${professor}. (نسخة تجريبية - الربط مع الباك إند لسه شغالين عليه)`);
    }, 2000);
  };

  return (
    <Card className="w-full max-w-2xl mx-auto shadow-2xl bg-white/40 backdrop-blur-xl border border-white/60 rounded-3xl overflow-hidden relative">
      <div className="absolute top-0 inset-x-0 h-1 bg-gradient-to-r from-emerald-400 via-teal-500 to-cyan-500"></div>
      <CardHeader className="pt-8 pb-6">
        <CardTitle className="text-3xl flex items-center justify-center gap-3 font-extrabold bg-clip-text text-transparent bg-gradient-to-br from-slate-900 to-slate-600">
          <Volume2 className="h-8 w-8 text-teal-500" />
          اسأل أستاذك الافتراضي
        </CardTitle>
        <CardDescription className="text-center text-base font-medium text-slate-500 mt-2">
          اكتب سؤالك، اختار الدكتور، وجرب شكل الإجابة اللي هتوصلك من النظام.
        </CardDescription>
      </CardHeader>
      <form onSubmit={handleAskProfessor}>
        <CardContent className="space-y-6 px-8">
          <div className="space-y-3">
            <Label htmlFor="professor" className="text-sm font-semibold text-slate-700 ml-1">اختار الأستاذ</Label>
            <Select value={professor} onValueChange={setProfessor} required>
              <SelectTrigger id="professor" className="w-full bg-white/50 border-white/60 h-12 rounded-xl shadow-sm focus:ring-emerald-500/50">
                <SelectValue placeholder="مين تحب يجاوبك؟" />
              </SelectTrigger>
              <SelectContent className="rounded-xl border-white/60 bg-white/80 backdrop-blur-lg">
                <SelectItem value="geddo" className="rounded-lg cursor-pointer">Dr. Geddo</SelectItem>
                <SelectItem value="hammad" className="rounded-lg cursor-pointer">Dr. Hammad</SelectItem>
                <SelectItem value="hanan" className="rounded-lg cursor-pointer">Dr. Hanan</SelectItem>
                <SelectItem value="mk" className="rounded-lg cursor-pointer">Dr. MK</SelectItem>
              </SelectContent>
            </Select>
          </div>
          
          <div className="space-y-3">
            <Label htmlFor="question" className="text-sm font-semibold text-slate-700 ml-1">السؤال</Label>
            <Textarea
              id="question"
              placeholder="اكتب سؤالك هنا... مثال: إزاي أبدأ أتعلم machine learning بشكل عملي؟"
              className="resize-none h-36 bg-white/50 border-white/60 rounded-xl shadow-sm focus:ring-emerald-500/50 p-4 text-base"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              required
            />
          </div>
        </CardContent>
        <CardFooter className="px-8 pb-8 pt-4">
          <Button 
            type="submit" 
            className="w-full h-12 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-600 hover:from-emerald-600 hover:to-teal-700 text-white font-semibold text-lg shadow-lg hover:shadow-emerald-500/25 transition-all" 
            disabled={isGeneratingAnswer || !question || !professor}
          >
            {isGeneratingAnswer && <Loader2 className="mr-2 h-5 w-5 animate-spin" />}
            {isGeneratingAnswer ? "جاري تجهيز الإجابة..." : "اعرض الإجابة التجريبية"}
          </Button>
        </CardFooter>
      </form>
    </Card>
  );
}
