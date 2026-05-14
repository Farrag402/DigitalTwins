import { useState, useRef } from "react";
import { Play, Pause, Phone } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";

interface ProfessorCardProps {
  id: string;
  name: string;
  description: string;
  audioSrc: string;
  avatarInitials: string;
  avatarSrc: string;
  onStartCall: (professorId: string, professorName: string) => void;
}

export function ProfessorCard({
  id,
  name,
  description,
  audioSrc,
  avatarInitials,
  avatarSrc,
  onStartCall
}: ProfessorCardProps) {
  const [isPlaying, setIsPlaying] = useState(false);
  const [progress, setProgress] = useState(0);
  const audioRef = useRef<HTMLAudioElement>(null);
  const baseWaveformHeights = [35, 60, 45, 75, 40, 65, 30, 70, 50, 80, 45, 68, 38, 72, 55, 62, 42, 78, 48, 66, 36, 74, 52, 64];
  const waveformHeights = Array.from({ length: 50 }, (_, index) => baseWaveformHeights[index % baseWaveformHeights.length]);
  const playedBars = Math.round((progress / 100) * waveformHeights.length);

  const togglePlay = () => {
    if (audioRef.current) {
      if (isPlaying) {
        audioRef.current.pause();
      } else {
        audioRef.current.play();
      }
      setIsPlaying(!isPlaying);
    }
  };

  const handleTimeUpdate = () => {
    if (audioRef.current) {
      const current = audioRef.current.currentTime;
      const duration = audioRef.current.duration;
      if (duration) {
        setProgress((current / duration) * 100);
      }
    }
  };

  const handleEnded = () => {
    setIsPlaying(false);
    setProgress(0);
  };

  return (
    <Card className="flex flex-col h-full overflow-hidden transition-all duration-300 hover:shadow-2xl hover:-translate-y-1 bg-white/40 backdrop-blur-xl border border-white/60 shadow-xl rounded-3xl">
      <CardHeader className="flex-grow cursor-default select-none">
        <div className="flex items-center gap-4">
          <Avatar className="h-16 w-16 ring-2 ring-white shadow-sm overflow-hidden">
            <AvatarImage src={avatarSrc} alt={name} className="object-cover w-full h-full" />
            <AvatarFallback className="text-lg bg-gradient-to-tr from-emerald-100 to-teal-100 text-slate-700 font-medium">{avatarInitials}</AvatarFallback>
          </Avatar>
          <div>
            <CardTitle className="text-xl font-bold bg-clip-text text-transparent bg-gradient-to-br from-slate-800 to-slate-500">{name}</CardTitle>
            <CardDescription className="line-clamp-3 mt-1 text-slate-600 font-medium leading-relaxed">{description}</CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent className="bg-white/30 p-5 border-t border-white/40 mt-auto rounded-b-3xl">
        <div className="flex items-center gap-4">
          <Button
            type="button"
            className="h-12 px-4 rounded-full shadow-sm bg-gradient-to-r from-emerald-500 to-teal-600 hover:from-emerald-600 hover:to-teal-700 text-white shrink-0"
            onClick={() => onStartCall(id, name)}
          >
            <Phone className="h-4 w-4 mr-2" />
            Start Call
          </Button>
          <Button
            variant="outline"
            size="icon"
            className="h-12 w-12 rounded-full shrink-0 shadow-sm border-white/60 bg-white/50 hover:bg-white text-slate-800 transition-all hover:scale-105"
            onClick={togglePlay}
          >
            {isPlaying ? <Pause className="h-5 w-5" /> : <Play className="h-5 w-5 mr-1" />}
          </Button>
          <div className="waveform-visualization flex-1 h-12 bg-white/50 rounded-xl overflow-hidden shadow-inner border border-white/20 px-2 cursor-default select-none">
            <div className="h-full flex items-center justify-between gap-[2px]">
              {waveformHeights.map((height, index) => (
                <div
                  key={`${name}-wave-${index}`}
                  className={`w-[4px] rounded-full transition-all duration-150 ${
                    index < playedBars
                      ? "bg-gradient-to-t from-emerald-400 to-teal-400 shadow-[0_0_8px_rgba(45,212,191,0.55)]"
                      : "bg-slate-300/70"
                  } ${isPlaying ? "opacity-100" : "opacity-80"}`}
                  style={{ height: `${height}%` }}
                />
              ))}
            </div>
          </div>
        </div>
        <audio
          ref={audioRef}
          src={audioSrc}
          onTimeUpdate={handleTimeUpdate}
          onEnded={handleEnded}
          className="hidden"
        />
      </CardContent>
    </Card>
  );
}
