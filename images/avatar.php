<?php
// Génère un avatar par défaut (image SVG)
header('Content-Type: image/svg+xml');

// Générer une couleur basée sur l'ID ou utiliser une couleur par défaut
$colors = ['#3498db', '#e74c3c', '#2ecc71', '#f39c12', '#9b59b6', '#1abc9c'];
$color = $colors[array_rand($colors)];

echo <<<SVG
<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">
  <circle cx="32" cy="32" r="32" fill="$color"/>
  <circle cx="32" cy="24" r="10" fill="white" opacity="0.8"/>
  <path d="M 16 48 Q 16 36 32 36 Q 48 36 48 48" fill="white" opacity="0.8"/>
</svg>
SVG;
?>
