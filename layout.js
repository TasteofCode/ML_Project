import '../styles/globals.css'

export const metadata = {
  title: 'Real-Time IMU Gesture Recognition & Control Dashboard (FastAPI + ESP32)',
  description: 'Industrial-grade real-time gesture classification panel using MPU6050, ESP32 over WebSockets, and pre-trained Support Vector Machine (SVM) ensemble models.',
  keywords: 'ESP32, MPU6050, WebSockets, FastAPI, Gesture Recognition, SVM, scikit-learn, Machine Learning Inference',
}

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <head>
        <link rel="icon" href="/favicon.ico" sizes="any" />
      </head>
      <body className="font-tahoma antialiased bg-xp-grayFace">
        {children}
      </body>
    </html>
  )
}
